from __future__ import annotations

import hashlib
import mimetypes
import re
from collections import defaultdict
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID, uuid4
from zipfile import BadZipFile, ZipFile

from openpyxl import load_workbook
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import selectinload

from ..database import SessionLocal, set_request_context
from ..db_models import ImportJobRow
from ..file_security_models import MediaObjectRow
from ..identity_models import TenantRow
from ..model_mixins import utcnow
from ..product_center_models import SKU_TEMPLATE_SOURCE_OPTION_KEY, SkuRow
from ..product_supplier_models import ProductCategoryRow, ProductImageRow, ProductRow
from ..public_catalog_models import PublicCatalogOfferRow


PRODUCT_TEMPLATE_SHEET = "商品列表"
PRODUCT_TEMPLATE_HEADERS = (
    "商品名称",
    "商品分类",
    "商品型号",
    "商品价格",
    "商品描述",
    "备注",
    "标签",
    "商品图片1",
    "商品图片2",
    "商品图片3",
    "商品图片4",
    "商品图片5",
    "商品图片6",
    "商品图片7",
    "商品图片8",
    "商品图片9",
    "商品图片10",
)
MAX_TEMPLATE_ROWS = 20_000
MAX_ARCHIVE_ENTRIES = 5_000
MAX_UNCOMPRESSED_BYTES = 250 * 1024 * 1024
PRICE_QUANTUM = Decimal("0.01")
MAX_UNIT_PRICE = Decimal("999999999999999999.99")
MAX_TAGS = 20
MAX_TAG_LENGTH = 80
MAX_CATEGORY_NAME_LENGTH = 200
TEMPLATE_SOURCE_KEY = SKU_TEMPLATE_SOURCE_OPTION_KEY
TEMPLATE_SOURCE_VALUE = "PRODUCT_TEMPLATE"
TEMPLATE_IMAGE_BUCKET = "product-template"


class ProductTemplateValidationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ProductTemplateRow:
    row_number: int
    name: str
    category: str
    sku_code: str
    unit_price: Decimal | None
    description: str | None
    note: str | None
    tags: tuple[str, ...]
    default_moq: Decimal | None
    image_urls: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProductTemplateParseResult:
    rows: tuple[ProductTemplateRow, ...]
    warnings: tuple[str, ...]
    skipped_rows: int


@dataclass(frozen=True, slots=True)
class ProductTemplateImportResult:
    status: str
    imported: int = 0
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped: int = 0
    warnings: tuple[str, ...] = ()
    message: str | None = None


def _cell_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return format(value, ".15g")
    return str(value).strip()


def _decimal(value: object, *, field: str, row_number: int) -> Decimal:
    text = _cell_text(value).replace(",", "")
    if len(text) > 64:
        raise ProductTemplateValidationError(
            f"第 {row_number} 行的{field}超出 Numeric(20,2) 可存储范围。"
        )
    try:
        number = Decimal(text)
    except (InvalidOperation, ValueError) as exc:
        raise ProductTemplateValidationError(
            f"第 {row_number} 行的{field}不是有效数字。"
        ) from exc
    if not number.is_finite() or number < 0:
        raise ProductTemplateValidationError(
            f"第 {row_number} 行的{field}必须是大于或等于 0 的数字。"
        )
    # PostgreSQL Numeric(20,2) permits at most 18 integer digits. Quantize
    # before persistence so SQLite and PostgreSQL apply the exact same rule.
    if number >= MAX_UNIT_PRICE + Decimal("0.005"):
        raise ProductTemplateValidationError(
            f"第 {row_number} 行的{field}超出 Numeric(20,2) 可存储范围。"
        )
    try:
        with localcontext() as context:
            context.prec = 32
            number = number.quantize(PRICE_QUANTUM, rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:
        raise ProductTemplateValidationError(
            f"第 {row_number} 行的{field}超出 Numeric(20,2) 可存储范围。"
        ) from exc
    if number > MAX_UNIT_PRICE:
        raise ProductTemplateValidationError(
            f"第 {row_number} 行的{field}超出 Numeric(20,2) 可存储范围。"
        )
    return number


def _normalize_sku_code(value: object) -> str:
    """Return the canonical SKU identity used by XLSX and tenant lookup."""

    return _cell_text(value).strip().upper()


def _normalize_tags(value: object, *, row_number: int) -> tuple[str, ...]:
    text = _cell_text(value)
    if not text:
        return ()
    tags: list[str] = []
    seen: set[str] = set()
    for raw_tag in re.split(r"[,，;；、|\r\n]+", text):
        tag = raw_tag.strip()
        if not tag:
            continue
        if len(tag) > MAX_TAG_LENGTH:
            raise ProductTemplateValidationError(
                f"第 {row_number} 行的标签“{tag[:12]}…”超过 {MAX_TAG_LENGTH} 个字符，"
                "未执行本次全量同步。"
            )
        normalized = tag.casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        tags.append(tag)
        if len(tags) > MAX_TAGS:
            raise ProductTemplateValidationError(
                f"第 {row_number} 行最多填写 {MAX_TAGS} 个标签，"
                "未执行本次全量同步。"
            )
    return tuple(tags)


def _normalize_category_path(value: object, *, row_number: int) -> tuple[str, ...]:
    """Normalize the template's human-readable category path.

    A single segment creates a level-one category. ``A/B`` creates level one
    ``A`` and level two ``B``. Deeper or empty paths are rejected so imported
    data can never silently create an unsupported hierarchy.
    """

    text = _cell_text(value).replace("／", "/")
    parts = tuple(part.strip() for part in text.split("/"))
    if not text or any(not part for part in parts):
        raise ProductTemplateValidationError(
            f"第 {row_number} 行的商品分类格式无效；请填写“一级分类”或“一级分类/二级分类”。"
        )
    if len(parts) > 2:
        raise ProductTemplateValidationError(
            f"第 {row_number} 行的商品分类超过两级；最多填写“一级分类/二级分类”。"
        )
    if any(len(part) > MAX_CATEGORY_NAME_LENGTH for part in parts):
        raise ProductTemplateValidationError(
            f"第 {row_number} 行的分类名称超过 {MAX_CATEGORY_NAME_LENGTH} 个字符。"
        )
    return parts


def _valid_image_url(value: object) -> str | None:
    url = _cell_text(value)
    if not url:
        return None
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or len(url) > 1024:
        return None
    return url


def _inspect_archive(path: Path) -> None:
    try:
        with ZipFile(path) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_ARCHIVE_ENTRIES:
                raise ProductTemplateValidationError("Excel 文件包含过多内部条目，无法安全解析。")
            uncompressed = sum(max(0, entry.file_size) for entry in entries)
            if uncompressed > MAX_UNCOMPRESSED_BYTES:
                raise ProductTemplateValidationError("Excel 解压后体积过大，无法安全解析。")
            if not any(entry.filename.startswith("xl/") for entry in entries):
                raise ProductTemplateValidationError("文件不是有效的 XLSX 工作簿。")
    except BadZipFile as exc:
        raise ProductTemplateValidationError("文件不是有效的 XLSX 工作簿。") from exc


def parse_product_template(path: Path) -> ProductTemplateParseResult:
    if path.suffix.lower() != ".xlsx":
        raise ProductTemplateValidationError("只支持固定格式的 .xlsx 商品模版。")
    _inspect_archive(path)
    try:
        workbook = load_workbook(path, read_only=True, data_only=False)
    except (OSError, ValueError, BadZipFile) as exc:
        raise ProductTemplateValidationError("商品模版无法读取，请重新导出为 XLSX。") from exc

    try:
        if PRODUCT_TEMPLATE_SHEET not in workbook.sheetnames:
            raise ProductTemplateValidationError(
                f"缺少工作表“{PRODUCT_TEMPLATE_SHEET}”。"
            )
        sheet = workbook[PRODUCT_TEMPLATE_SHEET]
        received_headers = tuple(
            _cell_text(sheet.cell(row=1, column=index).value)
            for index in range(1, len(PRODUCT_TEMPLATE_HEADERS) + 1)
        )
        max_column = sheet.max_column or len(PRODUCT_TEMPLATE_HEADERS)
        extra_headers = [
            _cell_text(sheet.cell(row=1, column=index).value)
            for index in range(len(PRODUCT_TEMPLATE_HEADERS) + 1, max_column + 1)
            if _cell_text(sheet.cell(row=1, column=index).value)
        ]
        if received_headers != PRODUCT_TEMPLATE_HEADERS or extra_headers:
            raise ProductTemplateValidationError(
                "表头与固定商品模版不一致，请使用“商品模版.xlsx”的原始列名和顺序。"
            )
        if sheet.max_row is not None and max(0, sheet.max_row - 1) > MAX_TEMPLATE_ROWS:
            raise ProductTemplateValidationError(
                f"单次最多导入 {MAX_TEMPLATE_ROWS} 行商品。"
            )

        rows: list[ProductTemplateRow] = []
        warnings: list[str] = []
        first_row_by_sku: dict[str, int] = {}
        skipped_rows = 0
        for row_number, values in enumerate(
            sheet.iter_rows(
                min_row=2,
                max_col=len(PRODUCT_TEMPLATE_HEADERS),
                values_only=True,
            ),
            start=2,
        ):
            if row_number > MAX_TEMPLATE_ROWS + 1:
                raise ProductTemplateValidationError(
                    f"单次最多导入 {MAX_TEMPLATE_ROWS} 行商品。"
                )
            if not any(_cell_text(value) for value in values):
                continue
            if any(isinstance(value, str) and value.lstrip().startswith("=") for value in values):
                raise ProductTemplateValidationError(
                    f"第 {row_number} 行包含公式。完整商品模版只接受固定值，请先将公式转换为数值或文本。"
                )

            name = _cell_text(values[0])
            category_text = _cell_text(values[1])
            sku_code = _normalize_sku_code(values[2])
            missing = [
                label
                for label, value in (
                    ("商品名称", name),
                    ("商品分类", category_text),
                    ("商品型号", sku_code),
                )
                if not value
            ]
            if missing:
                raise ProductTemplateValidationError(
                    f"第 {row_number} 行缺少{'、'.join(missing)}，未执行本次全量同步。"
                )
            category_parts = _normalize_category_path(
                category_text, row_number=row_number
            )
            category = "/".join(category_parts)
            if len(name) > 500 or len(category) > 401 or len(sku_code) > 160:
                raise ProductTemplateValidationError(
                    f"第 {row_number} 行文本超过字段长度限制，未执行本次全量同步。"
                )
            if sku_code in first_row_by_sku:
                warnings.append(
                    f"第 {row_number} 行商品型号“{sku_code}”与第 "
                    f"{first_row_by_sku[sku_code]} 行重复，已保留首次出现的记录。"
                )
                skipped_rows += 1
                continue

            unit_price: Decimal | None = None
            if _cell_text(values[3]):
                try:
                    unit_price = _decimal(values[3], field="商品价格", row_number=row_number)
                except ProductTemplateValidationError as exc:
                    raise ProductTemplateValidationError(
                        f"{exc}未执行本次全量同步。"
                    ) from exc
            else:
                warnings.append(
                    f"第 {row_number} 行缺少商品价格，商品会进入商品库但暂不发布到前台。"
                )

            note = _cell_text(values[5]) or None
            tags = _normalize_tags(values[6], row_number=row_number)

            image_urls: list[str] = []
            for image_index, value in enumerate(values[7:], start=1):
                if not _cell_text(value):
                    continue
                image_url = _valid_image_url(value)
                if image_url is None:
                    raise ProductTemplateValidationError(
                        f"第 {row_number} 行商品图片{image_index}不是有效的 HTTP(S) 链接，"
                        "未执行本次全量同步。"
                    )
                if image_url not in image_urls:
                    image_urls.append(image_url)

            first_row_by_sku[sku_code] = row_number
            rows.append(
                ProductTemplateRow(
                    row_number=row_number,
                    name=name,
                    category=category,
                    sku_code=sku_code,
                    unit_price=unit_price,
                    description=_cell_text(values[4]) or None,
                    note=note,
                    tags=tags,
                    default_moq=None,
                    image_urls=tuple(image_urls),
                )
            )
        if not rows:
            raise ProductTemplateValidationError("模版中没有可导入的有效商品。")
        return ProductTemplateParseResult(
            rows=tuple(rows),
            warnings=tuple(warnings),
            skipped_rows=skipped_rows,
        )
    finally:
        workbook.close()


def _category_code(name: str) -> str:
    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:12].upper()
    return f"TPL-{digest}"


def _product_code(sku_code: str) -> str:
    # Product code is an internal, deterministic ownership marker. Keeping it
    # independent of the display SKU also guarantees one product per SKU.
    digest = hashlib.sha256(sku_code.encode("utf-8")).hexdigest()[:24].upper()
    return f"TPL-{digest}"


def _alternate_product_code(sku_code: str) -> str:
    digest = hashlib.sha256(f"PRODUCT_TEMPLATE:{sku_code}".encode("utf-8")).hexdigest()
    return f"TPLX-{digest[:48].upper()}"


def _template_option_values(
    note: str | None,
    *,
    existing: dict[str, object] | None = None,
) -> dict[str, object]:
    # The template owns its internal marker and the free-text note, but it
    # must not erase variant attributes maintained elsewhere in the product
    # center (for example color or size).
    values: dict[str, object] = dict(existing or {})
    values[TEMPLATE_SOURCE_KEY] = {
        "source": TEMPLATE_SOURCE_VALUE,
        "schema": 1,
    }
    if note:
        values["备注"] = note
    else:
        values.pop("备注", None)
    return values


def _is_template_managed_sku(sku: SkuRow) -> bool:
    marker = sku.option_values.get(TEMPLATE_SOURCE_KEY)
    return (
        isinstance(marker, dict)
        and marker.get("source") == TEMPLATE_SOURCE_VALUE
    )


def _fail_import(
    session,
    *,
    job: ImportJobRow,
    message: str,
) -> ProductTemplateImportResult:
    job.status = "failed"
    job.progress = 100
    job.warnings_count = max(1, job.warnings_count)
    job.error_message = message
    job.completed_at = utcnow()
    session.commit()
    return ProductTemplateImportResult(
        status="failed",
        warnings=(message,),
        message=message,
    )


def _image_content_type(url: str) -> str:
    content_type, _encoding = mimetypes.guess_type(urlsplit(url).path)
    return content_type if content_type and content_type.startswith("image/") else "image/jpeg"


def _filename_from_url(url: str) -> str:
    filename = Path(urlsplit(url).path).name
    return filename[:500] or "product-image"


def _load_image_map(
    session,
    *,
    tenant_id: UUID,
    image_urls: set[str],
) -> dict[str, ProductImageRow]:
    result: dict[str, ProductImageRow] = {}
    urls = list(image_urls)
    for start in range(0, len(urls), 500):
        chunk = urls[start : start + 500]
        rows = session.scalars(
            select(ProductImageRow)
            .where(
                ProductImageRow.tenant_id == tenant_id,
                ProductImageRow.object_key.in_(chunk),
            )
            .execution_options(include_deleted=True)
        ).all()
        result.update({row.object_key: row for row in rows})
    return result


def process_product_template_import(
    job_id: str,
    *,
    tenant_id: UUID,
    source_path: Path,
) -> ProductTemplateImportResult:
    with SessionLocal() as session:
        set_request_context(
            session,
            organization_id=UUID(int=0),
            tenant_id=tenant_id,
            user_id=UUID(int=0),
        )
        statement = (
            select(ImportJobRow)
            .options(selectinload(ImportJobRow.source_file))
            .where(
                ImportJobRow.id == job_id,
                ImportJobRow.tenant_id == tenant_id,
            )
        )
        job = session.scalar(statement)
        if job is None:
            raise RuntimeError("product template import job was not found")
        job.status = "parsing"
        job.progress = 25
        session.commit()

        try:
            parsed = parse_product_template(source_path)
        except ProductTemplateValidationError as exc:
            session.rollback()
            job = session.scalar(statement)
            if job is None:
                raise RuntimeError("product template import job disappeared") from exc
            job.status = "failed"
            job.progress = 100
            job.warnings_count = max(1, job.warnings_count)
            job.error_message = str(exc)
            job.completed_at = utcnow()
            session.commit()
            return ProductTemplateImportResult(status="failed", warnings=(str(exc),), message=str(exc))

        job = session.scalar(statement)
        if job is None:
            raise RuntimeError("product template import job disappeared")
        # Serialize authoritative snapshots per tenant. PostgreSQL takes a row
        # lock here; SQLite already serializes writers. Once the lock is held,
        # an older retry is rejected if a newer snapshot has already won.
        tenant = session.scalar(
            select(TenantRow)
            .where(TenantRow.id == tenant_id)
            .with_for_update()
        )
        if tenant is None:
            return _fail_import(
                session,
                job=job,
                message="当前租户不存在或已停用，未执行本次商品模版同步。",
            )
        newer_published_job_id = session.scalar(
            select(ImportJobRow.id)
            .where(
                ImportJobRow.tenant_id == tenant_id,
                ImportJobRow.source_type == "PRODUCT_TEMPLATE",
                ImportJobRow.status == "published",
                ImportJobRow.id != job.id,
                or_(
                    ImportJobRow.created_at > job.created_at,
                    and_(
                        ImportJobRow.created_at == job.created_at,
                        ImportJobRow.id > job.id,
                    ),
                ),
            )
            .order_by(ImportJobRow.created_at.desc())
            .limit(1)
            .execution_options(include_deleted=True)
        )
        if newer_published_job_id is not None:
            message = (
                "本次商品模版早于已经生效的新版本，系统已跳过旧快照，"
                "不会覆盖当前商品库。"
            )
            job.status = "failed"
            job.progress = 100
            job.warnings_count = 1
            job.error_message = message
            job.completed_at = utcnow()
            session.commit()
            return ProductTemplateImportResult(
                status="superseded",
                warnings=(message,),
                message=message,
            )
        currency = tenant.default_currency
        media = (
            session.get(MediaObjectRow, job.source_file.media_object_id)
            if job.source_file.media_object_id
            else None
        )
        user_id = media.created_by_user_id if media else None
        now = utcnow()

        categories = {
            row.code: row
            for row in session.scalars(
                select(ProductCategoryRow)
                .where(
                    ProductCategoryRow.tenant_id == tenant_id,
                )
                .execution_options(include_deleted=True)
            ).all()
        }
        product_rows = session.scalars(
            select(ProductRow)
            .where(
                ProductRow.tenant_id == tenant_id,
            )
            .execution_options(include_deleted=True)
        ).all()
        products = {
            row.product_code: row
            for row in product_rows
            if row.product_code
        }
        sku_rows = session.scalars(
            select(SkuRow)
            .where(
                SkuRow.tenant_id == tenant_id,
            )
            .execution_options(include_deleted=True)
        ).all()
        sku_groups: dict[str, list[SkuRow]] = defaultdict(list)
        for sku_row in sku_rows:
            sku_groups[_normalize_sku_code(sku_row.sku_code)].append(sku_row)

        incoming_sku_codes = {row.sku_code for row in parsed.rows}
        conflicting_codes = sorted(
            code
            for code in incoming_sku_codes
            if len(sku_groups.get(code, ())) > 1
        )
        if conflicting_codes:
            return _fail_import(
                session,
                job=job,
                message=(
                    "租户商品库存在忽略大小写或首尾空白后重复的 SKU："
                    f"{'、'.join(conflicting_codes[:5])}。请先合并重复记录后再导入。"
                ),
            )

        skus = {
            code: rows[0]
            for code, rows in sku_groups.items()
            if len(rows) == 1
        }
        sku_rows_by_product: dict[UUID, list[SkuRow]] = defaultdict(list)
        for sku_row in sku_rows:
            sku_rows_by_product[sku_row.product_id].append(sku_row)
        products_by_id = {row.id: row for row in product_rows}
        existing_sku_ids = [row.id for row in sku_rows]
        offers = (
            {
                row.sku_id: row
                for row in session.scalars(
                    select(PublicCatalogOfferRow)
                    .where(
                        PublicCatalogOfferRow.tenant_id == tenant_id,
                        PublicCatalogOfferRow.sku_id.in_(existing_sku_ids),
                    )
                    .execution_options(include_deleted=True)
                ).all()
            }
            if existing_sku_ids
            else {}
        )
        all_image_urls = {
            url for template_row in parsed.rows for url in template_row.image_urls
        }
        images = _load_image_map(
            session,
            tenant_id=tenant_id,
            image_urls=all_image_urls,
        )
        template_images_by_product: dict[UUID, list[ProductImageRow]] = defaultdict(list)
        for image in session.scalars(
            select(ProductImageRow)
            .where(
                ProductImageRow.tenant_id == tenant_id,
                ProductImageRow.storage_provider == "EXTERNAL",
                ProductImageRow.bucket == TEMPLATE_IMAGE_BUCKET,
            )
            .execution_options(include_deleted=True)
        ).all():
            template_images_by_product[image.product_id].append(image)

        # Pre-plan product ownership before making changes. Existing SKUs with
        # siblings are split onto a dedicated product so row order can never
        # overwrite another SKU's name/category/description.
        planned_product_by_sku: dict[str, ProductRow | None] = {}
        planned_product_code_by_sku: dict[str, str | None] = {}
        for template_row in parsed.rows:
            sku = skus.get(template_row.sku_code)
            current_product = products_by_id.get(sku.product_id) if sku else None
            siblings = (
                [
                    row
                    for row in sku_rows_by_product.get(sku.product_id, ())
                    if row.id != sku.id
                ]
                if sku
                else []
            )
            if current_product is not None and not siblings:
                planned_product_by_sku[template_row.sku_code] = current_product
                planned_product_code_by_sku[template_row.sku_code] = None
                continue

            selected_product: ProductRow | None = None
            selected_code: str | None = None
            for candidate_code in (
                _product_code(template_row.sku_code),
                _alternate_product_code(template_row.sku_code),
            ):
                candidate = products.get(candidate_code)
                candidate_skus = (
                    sku_rows_by_product.get(candidate.id, ())
                    if candidate is not None
                    else ()
                )
                if candidate is None or not candidate_skus:
                    selected_product = candidate
                    selected_code = candidate_code
                    break
            if selected_code is None:
                return _fail_import(
                    session,
                    job=job,
                    message=(
                        f"SKU“{template_row.sku_code}”无法分配独立商品记录；"
                        "保留的模版商品编码已被其他 SKU 占用。"
                    ),
                )
            planned_product_by_sku[template_row.sku_code] = selected_product
            planned_product_code_by_sku[template_row.sku_code] = selected_code

        created = 0
        updated = 0
        unchanged = 0
        dirty_product_ids: set[UUID] = set()
        runtime_warnings = list(parsed.warnings)
        for template_row in parsed.rows:
            changed = False
            category_parts = tuple(template_row.category.split("/"))
            parent: ProductCategoryRow | None = None
            category: ProductCategoryRow | None = None
            for depth, category_name in enumerate(category_parts, start=1):
                category_path = "/".join(category_parts[:depth])
                category_code = _category_code(category_path)
                category = categories.get(category_code)
                category_values = {
                    "parent_id": parent.id if parent is not None else None,
                    "name": category_name,
                    "path": category_path,
                    "status": "ACTIVE",
                    "deleted_at": None,
                }
                if category is None:
                    category = ProductCategoryRow(
                        id=uuid4(),
                        tenant_id=tenant_id,
                        code=category_code,
                        **category_values,
                    )
                    session.add(category)
                    categories[category_code] = category
                    session.flush()
                    changed = True
                elif any(
                    getattr(category, key) != value
                    for key, value in category_values.items()
                ):
                    for key, value in category_values.items():
                        setattr(category, key, value)
                    category.version += 1
                    changed = True
                parent = category
            assert category is not None

            sku = skus.get(template_row.sku_code)
            product = planned_product_by_sku[template_row.sku_code]
            product_code = planned_product_code_by_sku[template_row.sku_code]
            is_new = sku is None
            if product is None:
                assert product_code is not None
                product = ProductRow(
                    id=uuid4(),
                    tenant_id=tenant_id,
                    product_code=product_code,
                    name=template_row.name,
                    description=template_row.description,
                    category_id=category.id,
                    status="ACTIVE",
                    default_unit="piece",
                    created_by=user_id,
                    updated_by=user_id,
                )
                session.add(product)
                products[product_code] = product
                products_by_id[product.id] = product
                # Product and category must exist before the composite SKU
                # foreign key is evaluated (notably by SQLite executemany).
                session.flush()
                changed = True
            else:
                product_values = {
                    "name": template_row.name,
                    "description": template_row.description,
                    "category_id": category.id,
                    "status": "ACTIVE",
                    "default_unit": product.default_unit or "piece",
                    "archived_at": None,
                    "deleted_at": None,
                }
                if any(getattr(product, key) != value for key, value in product_values.items()):
                    for key, value in product_values.items():
                        setattr(product, key, value)
                    product.current_version += 1
                    product.updated_by = user_id
                    changed = True

            if sku is None:
                sku = SkuRow(
                    id=uuid4(),
                    tenant_id=tenant_id,
                    product_id=product.id,
                    sku_code=template_row.sku_code,
                    name=template_row.name,
                    option_values=_template_option_values(template_row.note),
                    default_moq=template_row.default_moq,
                    moq_unit=None,
                    status="ACTIVE",
                    created_by_user_id=user_id,
                    updated_by_user_id=user_id,
                )
                session.add(sku)
                skus[sku.sku_code] = sku
                sku_rows.append(sku)
                sku_rows_by_product[product.id].append(sku)
                # Public offers reference the SKU through a composite tenant
                # foreign key, so establish the SKU before staging its offer.
                session.flush()
                changed = True
            else:
                old_product_id = sku.product_id
                sku_values = {
                    "product_id": product.id,
                    "sku_code": template_row.sku_code,
                    "name": template_row.name,
                    "option_values": _template_option_values(
                        template_row.note,
                        existing=sku.option_values,
                    ),
                    "default_moq": template_row.default_moq,
                    "moq_unit": None,
                    "status": "ACTIVE",
                    "deleted_at": None,
                }
                if any(getattr(sku, key) != value for key, value in sku_values.items()):
                    for key, value in sku_values.items():
                        setattr(sku, key, value)
                    sku.version += 1
                    sku.updated_by_user_id = user_id
                    changed = True
                if old_product_id != product.id:
                    sku_rows_by_product[old_product_id] = [
                        row
                        for row in sku_rows_by_product[old_product_id]
                        if row.id != sku.id
                    ]
                    sku_rows_by_product[product.id].append(sku)

            offer = offers.get(sku.id)
            offer_tags = list(template_row.tags)
            if offer is None and template_row.unit_price is not None:
                offer = PublicCatalogOfferRow(
                    id=uuid4(),
                    tenant_id=tenant_id,
                    sku_id=sku.id,
                    unit_price=template_row.unit_price,
                    currency=currency,
                    tags=offer_tags,
                    publication_status="PUBLISHED",
                    published_at=now,
                )
                session.add(offer)
                offers[sku.id] = offer
                changed = True
            elif offer is not None and template_row.unit_price is not None:
                offer_values = {
                    "unit_price": template_row.unit_price,
                    "currency": currency,
                    "tags": offer_tags,
                    "publication_status": "PUBLISHED",
                    "deleted_at": None,
                }
                if any(getattr(offer, key) != value for key, value in offer_values.items()):
                    for key, value in offer_values.items():
                        setattr(offer, key, value)
                    offer.published_at = now
                    changed = True
            elif offer is not None and offer.publication_status != "SUSPENDED":
                offer.publication_status = "SUSPENDED"
                changed = True

            desired_image_urls = set(template_row.image_urls)
            for old_image in template_images_by_product.get(product.id, ()):
                if (
                    old_image.object_key not in desired_image_urls
                    and old_image.deleted_at is None
                ):
                    old_image.deleted_at = now
                    changed = True

            for image_index, image_url in enumerate(template_row.image_urls):
                image = images.get(image_url)
                if image is not None and image.product_id != product.id:
                    runtime_warnings.append(
                        f"第 {template_row.row_number} 行图片链接已被其他商品使用，已跳过该图片。"
                    )
                    continue
                if image is None:
                    image = ProductImageRow(
                        id=uuid4(),
                        tenant_id=tenant_id,
                        product_id=product.id,
                        storage_provider="EXTERNAL",
                        bucket=TEMPLATE_IMAGE_BUCKET,
                        object_key=image_url,
                        original_filename=_filename_from_url(image_url),
                        content_type=_image_content_type(image_url),
                        byte_size=0,
                        sha256=hashlib.sha256(image_url.encode("utf-8")).hexdigest(),
                        image_role="MAIN" if image_index == 0 else "GALLERY",
                        sort_order=image_index,
                        approval_status="APPROVED",
                        alt_text=template_row.name,
                        created_by=user_id,
                    )
                    session.add(image)
                    images[image_url] = image
                    template_images_by_product[product.id].append(image)
                    changed = True
                else:
                    if image.storage_provider != "EXTERNAL":
                        runtime_warnings.append(
                            f"第 {template_row.row_number} 行图片链接与非外链图片冲突，已跳过该图片。"
                        )
                        continue
                    image_values = {
                        "bucket": TEMPLATE_IMAGE_BUCKET,
                        "deleted_at": None,
                        "image_role": "MAIN" if image_index == 0 else "GALLERY",
                        "sort_order": image_index,
                        "approval_status": "APPROVED",
                        "alt_text": template_row.name,
                    }
                    if any(
                        getattr(image, key) != value
                        for key, value in image_values.items()
                    ):
                        for key, value in image_values.items():
                            setattr(image, key, value)
                        changed = True
                    if image not in template_images_by_product[product.id]:
                        template_images_by_product[product.id].append(image)

            if is_new:
                created += 1
            elif changed:
                updated += 1
            else:
                unchanged += 1
            if changed and product.status == "ACTIVE":
                product.search_document_version = 0
                dirty_product_ids.add(product.id)

        # PRODUCT_TEMPLATE is a full snapshot, but only records explicitly
        # adopted by this importer are managed. Manual/non-template SKUs remain
        # untouched. This source marker makes the second and later imports safe.
        archived = 0
        for sku in sku_rows:
            if (
                not _is_template_managed_sku(sku)
                or _normalize_sku_code(sku.sku_code) in incoming_sku_codes
            ):
                continue

            sku_was_active = sku.status != "ARCHIVED" or sku.deleted_at is not None
            if sku_was_active:
                sku.status = "ARCHIVED"
                sku.deleted_at = None
                sku.version += 1
                sku.updated_by_user_id = user_id
                archived += 1

            offer = offers.get(sku.id)
            if offer is not None and offer.publication_status != "SUSPENDED":
                offer.publication_status = "SUSPENDED"

            for image in template_images_by_product.get(sku.product_id, ()):
                if image.deleted_at is None:
                    image.deleted_at = now

            product = products_by_id.get(sku.product_id)
            if product is None:
                continue
            product_skus = [
                row
                for row in sku_rows_by_product.get(product.id, ())
            ]
            if (
                product_skus
                and all(_is_template_managed_sku(row) for row in product_skus)
                and all(row.status == "ARCHIVED" for row in product_skus)
                and (product.status != "ARCHIVED" or product.archived_at is None)
            ):
                product.status = "ARCHIVED"
                product.archived_at = now
                product.current_version += 1
                product.updated_by = user_id

        imported = created + updated + unchanged
        warning_summary = "；".join(runtime_warnings[:3])
        index_summary = (
            f"，待更新智能索引 {len(dirty_product_ids)}"
            if dirty_product_ids
            else ""
        )
        result_summary = (
            f"商品模版导入完成：新建 {created}，更新 {updated}，"
            f"未变化 {unchanged}，归档 {archived}，跳过 {parsed.skipped_rows}"
            f"{index_summary}。"
        )
        job.products_count = imported
        job.warnings_count = len(runtime_warnings)
        job.progress = 100
        job.status = "published"
        job.error_message = (
            f"{result_summary}{' ' + warning_summary if warning_summary else ''}"
        )
        job.completed_at = now
        session.commit()
        return ProductTemplateImportResult(
            status="published",
            imported=imported,
            created=created,
            updated=updated,
            unchanged=unchanged,
            skipped=parsed.skipped_rows,
            warnings=tuple(runtime_warnings),
            message=result_summary,
        )
