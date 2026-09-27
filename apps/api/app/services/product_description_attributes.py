"""Deterministic extraction and synchronization for description attributes."""

from __future__ import annotations

import re
from decimal import Decimal
from hashlib import sha256
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..product_center_models import AttributeDefinitionRow
from ..product_supplier_models import ProductAttributeRow, ProductRow


_LINE_PATTERN = re.compile(r"^\s*([^:：\r\n;；]{1,100}?)\s*[:：]\s*(.*?)\s*$")
_KEY_NORMALIZE_PATTERN = re.compile(r"[\s_\-/:：,.，。()（）\[\]【】]+")
_INLINE_LABEL_PATTERN = re.compile(r"(?:^|[\s,，。|])([^\s,，。|:：]{1,30})\s*$")
_TRAILING_CHINESE_PATTERN = re.compile(r"[\u4e00-\u9fff]{2,30}$")
_COLON_PATTERN = re.compile(r"[:：]")
# Without a separator, Chinese text on both sides of a field name is
# inherently ambiguous. Recognize common catalogue labels as suffixes while
# leaving the preceding description text in the previous field's value.
_INLINE_LABEL_HINTS = tuple(sorted({
    "支持系统", "操作系统", "适用系统", "蓝牙版本", "无线距离", "连接距离",
    "传输距离", "连接方式", "无线频率", "工作频率", "电池容量", "充电时间",
    "续航时间", "产品尺寸", "包装尺寸", "商品尺寸", "产品重量", "包装重量",
    "产品型号", "商品型号", "防水等级", "防护等级", "认证标准", "额定电压",
    "额定功率", "工作电压", "工作电流", "适用对象", "适用范围", "装箱数量",
    "装箱数", "毛重", "净重", "材质", "颜色", "尺寸", "规格", "型号",
    "重量", "容量", "功率", "电压", "电流", "频率", "长度", "宽度",
    "高度", "证书", "认证", "品牌", "产地", "保修期", "用途", "功能",
}, key=len, reverse=True))


def description_attribute_key(value: object) -> str:
    return _KEY_NORMALIZE_PATTERN.sub("", str(value or "").casefold().strip())


def description_attribute_definition_key(display_name: str) -> str:
    digest = sha256(description_attribute_key(display_name).encode("utf-8")).hexdigest()[:20]
    return f"auto_{digest}"


def _inline_label_start(fragment: str, value_start: int, colon_index: int) -> int | None:
    """Find a plausible next field name before a colon in a single line."""

    if fragment[colon_index + 1 :].startswith("//"):
        return None
    before_colon = fragment[value_start:colon_index].rstrip()
    spaced = _INLINE_LABEL_PATTERN.search(before_colon)
    if spaced is not None:
        label = spaced.group(1)
        label_start = value_start + spaced.start(1)
        if (
            label_start > value_start
            and fragment[value_start:label_start].strip()
            and any(character.isalpha() for character in label)
            and description_attribute_key(label) not in {"http", "https"}
        ):
            return label_start

    # When ASCII/numeric value text runs straight into a Chinese label, the
    # entire trailing Chinese run is usually the field name. "要求" is a
    # common value ending, so defer that ambiguous case to known suffixes.
    trailing_chinese = _TRAILING_CHINESE_PATTERN.search(before_colon)
    if (
        trailing_chinese is not None
        and trailing_chinese.start() > 0
        and not trailing_chinese.group().startswith("要求")
    ):
        label_start = value_start + trailing_chinese.start()
        if fragment[value_start:label_start].strip():
            return label_start

    for label in _INLINE_LABEL_HINTS:
        if before_colon.endswith(label):
            label_start = value_start + len(before_colon) - len(label)
            if label_start > value_start and fragment[value_start:label_start].strip():
                return label_start

    return None


def _split_inline_attributes(fragment: str) -> tuple[tuple[str, str], ...]:
    first = _LINE_PATTERN.match(fragment)
    if first is None:
        return ()
    markers: list[tuple[str, int, int]] = [
        (first.group(1), first.start(1), first.start(2))
    ]
    for colon in _COLON_PATTERN.finditer(fragment, first.start(2)):
        label_start = _inline_label_start(fragment, markers[-1][2], colon.start())
        if label_start is None:
            continue
        markers.append((fragment[label_start:colon.start()].strip(), label_start, colon.end()))
    return tuple(
        (name, fragment[value_start:markers[index + 1][1] if index + 1 < len(markers) else len(fragment)])
        for index, (name, _label_start, value_start) in enumerate(markers)
    )


def extract_description_attributes(
    description: str | None,
) -> tuple[tuple[str, str], ...]:
    """Extract unique ``name: value`` pairs while preserving source values."""

    if not description or not description.strip():
        return ()
    result: list[tuple[str, str]] = []
    by_key: dict[str, int] = {}
    fragments = re.split(
        r"[\r\n]+|[;；](?=\s*[^:：;；\r\n]{1,100}\s*[:：])",
        description,
    )
    for fragment in fragments:
        for raw_name, raw_value in _split_inline_attributes(fragment):
            name = re.sub(r"\s+", " ", raw_name).strip(" -_：:")
            value = re.sub(r"\s+", " ", raw_value).strip()
            normalized_name = description_attribute_key(name)
            if (
                not normalized_name
                or normalized_name in {"http", "https"}
                or not value
                or len(name) > 100
                or len(value) > 4000
            ):
                continue
            existing_index = by_key.get(normalized_name)
            if existing_index is None:
                by_key[normalized_name] = len(result)
                result.append((name, value))
                continue
            previous_name, previous_value = result[existing_index]
            values = [part.strip() for part in re.split(r"[；;]", previous_value) if part.strip()]
            if value not in values:
                result[existing_index] = (previous_name, f"{previous_value}；{value}")
    return tuple(result)


def _attribute_value(row: ProductAttributeRow) -> object:
    for value in (row.value_text, row.value_number, row.value_boolean, row.value_json):
        if value is not None:
            return value
    return None


def _set_text_value(row: ProductAttributeRow, value: str) -> None:
    row.value_text = value
    row.value_number = None
    row.value_boolean = None
    row.value_json = None


class ProductDescriptionAttributeSynchronizer:
    """Cache definitions and values while synchronizing one or many products."""

    def __init__(
        self,
        session: Session,
        *,
        tenant_id: UUID,
        product_ids: set[UUID],
    ) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.definitions = list(
            session.scalars(
                select(AttributeDefinitionRow).where(
                    AttributeDefinitionRow.tenant_id == tenant_id,
                    AttributeDefinitionRow.category_id.is_(None),
                )
            ).all()
        )
        self.definitions_by_name = {
            description_attribute_key(row.display_name): row
            for row in self.definitions
            if row.deleted_at is None
        }
        self.definitions_by_key = {
            row.attribute_key: row
            for row in self.definitions
            if row.deleted_at is None
        }
        self.automatic_definition_ids = {
            row.id
            for row in self.definitions
            if row.deleted_at is None and row.attribute_key.startswith("auto_")
        }
        self.attributes_by_product: dict[
            UUID, dict[UUID, ProductAttributeRow]
        ] = {product_id: {} for product_id in product_ids}
        self.loaded_product_ids: set[UUID] = set()
        if product_ids and self.automatic_definition_ids:
            self._load_products(product_ids)

    def _load_products(self, product_ids: set[UUID]) -> None:
        """Load existing automatic values once, keeping large imports bounded."""

        pending = product_ids - self.loaded_product_ids
        if not pending:
            return
        if self.automatic_definition_ids:
            for row in self.session.scalars(
                select(ProductAttributeRow).where(
                    ProductAttributeRow.tenant_id == self.tenant_id,
                    ProductAttributeRow.product_id.in_(pending),
                    ProductAttributeRow.attribute_definition_id.in_(
                        self.automatic_definition_ids
                    ),
                )
            ).all():
                if row.attribute_definition_id is not None:
                    self.attributes_by_product.setdefault(row.product_id, {})[
                        row.attribute_definition_id
                    ] = row
        self.loaded_product_ids.update(pending)

    def _definition(self, display_name: str) -> tuple[AttributeDefinitionRow, bool]:
        normalized_name = description_attribute_key(display_name)
        definition = self.definitions_by_name.get(normalized_name)
        if definition is None:
            definition = self.definitions_by_key.get(
                description_attribute_definition_key(display_name)
            )
        if definition is not None:
            return definition, False
        definition = AttributeDefinitionRow(
            tenant_id=self.tenant_id,
            category_id=None,
            attribute_key=description_attribute_definition_key(display_name),
            display_name=display_name,
            data_type="TEXT",
            unit_code=None,
            enum_values=None,
            is_required=False,
            is_variant=False,
            is_filterable=True,
            is_matchable=True,
            status="ACTIVE",
            version=1,
        )
        self.session.add(definition)
        self.session.flush()
        self.definitions.append(definition)
        self.definitions_by_name[normalized_name] = definition
        self.definitions_by_key[definition.attribute_key] = definition
        self.automatic_definition_ids.add(definition.id)
        return definition, True

    def sync(
        self,
        product: ProductRow,
        description: str | None,
        *,
        protected_attribute_ids: set[UUID] | None = None,
    ) -> bool:
        """Synchronize auto values without overwriting merchant-confirmed data."""

        protected_ids = protected_attribute_ids or set()
        existing_by_definition = self.attributes_by_product.setdefault(product.id, {})
        changed = False
        desired_definition_ids: set[UUID] = set()
        extracted = extract_description_attributes(description)
        for display_name, _value in extracted:
            definition, created = self._definition(display_name)
            changed = changed or created
            desired_definition_ids.add(definition.id)
        # Definitions may have been created above, so load existing values only
        # after the complete automatic definition set is known.
        self._load_products({product.id})
        existing_by_definition = self.attributes_by_product.setdefault(product.id, {})
        for display_name, value in extracted:
            definition = self.definitions_by_name[description_attribute_key(display_name)]
            attribute = existing_by_definition.get(definition.id)
            if attribute is None:
                attribute = ProductAttributeRow(
                    tenant_id=self.tenant_id,
                    product_id=product.id,
                    attribute_definition_id=definition.id,
                    attribute_key=definition.attribute_key,
                    confidence=Decimal("1"),
                    review_status="AI_SUGGESTED",
                )
                _set_text_value(attribute, value)
                self.session.add(attribute)
                existing_by_definition[definition.id] = attribute
                changed = True
                continue
            if attribute.id in protected_ids or attribute.review_status != "AI_SUGGESTED":
                continue
            if (
                attribute.attribute_key != definition.attribute_key
                or _attribute_value(attribute) != value
            ):
                attribute.attribute_key = definition.attribute_key
                _set_text_value(attribute, value)
                attribute.confidence = Decimal("1")
                changed = True

        for definition_id, attribute in list(existing_by_definition.items()):
            if (
                attribute.id not in protected_ids
                and definition_id in self.automatic_definition_ids
                and definition_id not in desired_definition_ids
                and attribute.review_status == "AI_SUGGESTED"
            ):
                self.session.delete(attribute)
                existing_by_definition.pop(definition_id, None)
                changed = True
        return changed


def sync_product_description_attributes(
    session: Session,
    *,
    tenant_id: UUID,
    product: ProductRow,
    description: str | None,
    protected_attribute_ids: set[UUID] | None = None,
) -> bool:
    synchronizer = ProductDescriptionAttributeSynchronizer(
        session,
        tenant_id=tenant_id,
        product_ids={product.id},
    )
    return synchronizer.sync(
        product,
        description,
        protected_attribute_ids=protected_attribute_ids,
    )
