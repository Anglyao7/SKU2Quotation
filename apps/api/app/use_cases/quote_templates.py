from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from ..adapters.object_storage import get_object_storage
from ..domain.errors import ApplicationError
from ..model_mixins import mark_deleted
from ..quote_template_models import QuoteExcelTemplateRow
from ..quote_template_schemas import (
    QuoteExcelColumn,
    QuoteExcelTemplateListResponse,
    QuoteExcelTemplateRenderSpec,
    QuoteExcelTemplateReparseRequest,
    QuoteExcelTemplateResponse,
    QuoteExcelTemplateUpdateRequest,
)
from ..repositories import quote_template_repository as repository
from ..services.quote_excel_templates import (
    QuoteTemplateInspection,
    QuoteTemplateParseError,
    inspect_quote_excel_template,
)
from ..services.public_quote_documents import render_default_quote_template_xlsx
from ..services.storage import UploadTooLargeError, store_upload


def _require_manage(permissions: frozenset[str]) -> None:
    if "quotation.create" not in permissions:
        raise ApplicationError(
            "PERMISSION_DENIED",
            "Permission is required: quotation.create",
            kind="forbidden",
        )


def _column_payload(inspection: QuoteTemplateInspection) -> list[dict[str, object]]:
    return [
        {
            "key": column.key,
            "index": column.index,
            "header": column.header,
            "samples": column.samples,
            "suggested_field": column.suggested_field,
        }
        for column in inspection.columns
    ]


def _response(row: QuoteExcelTemplateRow) -> QuoteExcelTemplateResponse:
    mappings = {
        str(key).upper(): value
        for key, value in (row.column_mappings or {}).items()
        if value
    }
    columns = [
        QuoteExcelColumn(
            **column,
            mapped_field=mappings.get(str(column.get("key", "")).upper()),
        )
        for column in (row.columns or [])
    ]
    return QuoteExcelTemplateResponse(
        id=row.id,
        name=row.name,
        original_filename=row.original_filename,
        byte_size=row.byte_size,
        sheet_names=row.sheet_names or [row.sheet_name],
        sheet_name=row.sheet_name,
        header_row=row.header_row,
        data_start_row=row.data_start_row,
        data_end_row=row.data_end_row,
        columns=columns,
        column_mappings=mappings,
        is_default=row.is_default,
        is_ready=bool(mappings),
        version=row.version,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _template_not_found() -> ApplicationError:
    return ApplicationError(
        "QUOTE_EXCEL_TEMPLATE_NOT_FOUND",
        "Quote Excel template was not found.",
        kind="not_found",
    )


def list_templates(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
) -> QuoteExcelTemplateListResponse:
    _require_manage(permissions)
    items = [
        _response(row)
        for row in repository.list_for_tenant(session, tenant_id=tenant_id)
    ]
    return QuoteExcelTemplateListResponse(items=items, total=len(items))


def download_system_default_template(*, permissions: frozenset[str]) -> bytes:
    _require_manage(permissions)
    return render_default_quote_template_xlsx()


async def upload_template(
    session: Session,
    *,
    tenant_id: UUID,
    user_id: UUID,
    permissions: frozenset[str],
    upload: object,
    name: str | None,
) -> QuoteExcelTemplateResponse:
    _require_manage(permissions)
    filename = str(getattr(upload, "filename", "") or "").strip()
    if Path(filename).suffix.casefold() != ".xlsx":
        raise ApplicationError(
            "QUOTE_EXCEL_TEMPLATE_TYPE_INVALID",
            "Only .xlsx quote templates are supported.",
        )
    template_id = uuid4()
    storage = get_object_storage()
    try:
        stored = await store_upload(
            upload,
            f"quote-template-{template_id.hex}",
            tenant_id=tenant_id,
            storage=storage,
        )
    except UploadTooLargeError as exc:
        raise ApplicationError(
            "QUOTE_EXCEL_TEMPLATE_TOO_LARGE",
            str(exc),
            kind="too_large",
        ) from exc

    source_key = f"tenants/{tenant_id}/quote-templates/{template_id}.xlsx"
    promoted = False
    committed = False
    try:
        with storage.materialize(stored.object_key) as path:
            inspection = inspect_quote_excel_template(path)
        storage.promote(
            quarantine_key=stored.object_key,
            source_key=source_key,
        )
        promoted = True
        suggested_mappings = {
            column.key: column.suggested_field
            for column in inspection.columns
            if column.suggested_field
        }
        row = QuoteExcelTemplateRow(
            id=template_id,
            tenant_id=tenant_id,
            name=(name or Path(filename).stem or "报价单模板").strip()[:160],
            original_filename=filename[:500],
            object_key=source_key,
            sha256=stored.sha256,
            byte_size=stored.byte_size,
            sheet_names=inspection.sheet_names,
            sheet_name=inspection.sheet_name,
            header_row=inspection.header_row,
            data_start_row=inspection.data_start_row,
            data_end_row=inspection.data_end_row,
            columns=_column_payload(inspection),
            column_mappings=suggested_mappings,
            is_default=False,
            version=1,
            created_by_user_id=user_id,
            updated_by_user_id=user_id,
        )
        session.add(row)
        session.commit()
        committed = True
        session.refresh(row)
        return _response(row)
    except QuoteTemplateParseError as exc:
        session.rollback()
        raise ApplicationError(
            "QUOTE_EXCEL_TEMPLATE_PARSE_FAILED",
            str(exc),
        ) from exc
    except Exception:
        session.rollback()
        raise
    finally:
        try:
            if promoted:
                if not committed:
                    storage.delete(source_key)
            else:
                storage.delete(stored.object_key)
        except Exception:
            # Upload/parse errors are the useful response for the merchant. A
            # temporary storage cleanup failure must not replace that response;
            # object-storage lifecycle cleanup can remove the orphan later.
            pass


def reparse_template(
    session: Session,
    *,
    tenant_id: UUID,
    template_id: UUID,
    user_id: UUID,
    permissions: frozenset[str],
    request: QuoteExcelTemplateReparseRequest,
) -> QuoteExcelTemplateResponse:
    _require_manage(permissions)
    row = repository.get_for_tenant(
        session,
        tenant_id=tenant_id,
        template_id=template_id,
    )
    if row is None:
        raise _template_not_found()
    storage = get_object_storage()
    try:
        with storage.materialize(row.object_key) as path:
            inspection = inspect_quote_excel_template(
                path,
                sheet_name=request.sheet_name,
                header_row=request.header_row,
            )
    except FileNotFoundError as exc:
        raise ApplicationError(
            "QUOTE_EXCEL_TEMPLATE_FILE_UNAVAILABLE",
            "The stored Excel template is temporarily unavailable.",
            kind="unavailable",
        ) from exc
    except QuoteTemplateParseError as exc:
        raise ApplicationError(
            "QUOTE_EXCEL_TEMPLATE_PARSE_FAILED",
            str(exc),
        ) from exc

    old_mappings = row.column_mappings or {}
    valid_keys = {column.key for column in inspection.columns}
    mappings = {
        key: field
        for key, field in old_mappings.items()
        if key in valid_keys
    }
    for column in inspection.columns:
        if column.key not in mappings and column.suggested_field:
            mappings[column.key] = column.suggested_field
    row.sheet_names = inspection.sheet_names
    row.sheet_name = inspection.sheet_name
    row.header_row = inspection.header_row
    row.data_start_row = inspection.data_start_row
    row.data_end_row = inspection.data_end_row
    row.columns = _column_payload(inspection)
    row.column_mappings = mappings
    row.is_default = False
    row.version += 1
    row.updated_by_user_id = user_id
    session.commit()
    session.refresh(row)
    return _response(row)


def update_template(
    session: Session,
    *,
    tenant_id: UUID,
    template_id: UUID,
    user_id: UUID,
    permissions: frozenset[str],
    request: QuoteExcelTemplateUpdateRequest,
) -> QuoteExcelTemplateResponse:
    _require_manage(permissions)
    row = repository.get_for_tenant(
        session,
        tenant_id=tenant_id,
        template_id=template_id,
    )
    if row is None:
        raise _template_not_found()
    valid_keys = {str(column.get("key", "")).upper() for column in row.columns}
    invalid_keys = sorted(set(request.column_mappings) - valid_keys)
    if invalid_keys:
        raise ApplicationError(
            "QUOTE_EXCEL_TEMPLATE_COLUMN_INVALID",
            "Mapped columns are not present in the selected header: "
            + ", ".join(invalid_keys),
        )
    if request.is_default:
        repository.clear_default(
            session,
            tenant_id=tenant_id,
            except_template_id=row.id,
        )
    row.name = request.name
    row.column_mappings = dict(request.column_mappings)
    row.is_default = request.is_default
    row.version += 1
    row.updated_by_user_id = user_id
    session.commit()
    session.refresh(row)
    return _response(row)


def delete_template(
    session: Session,
    *,
    tenant_id: UUID,
    template_id: UUID,
    permissions: frozenset[str],
) -> None:
    _require_manage(permissions)
    row = repository.get_for_tenant(
        session,
        tenant_id=tenant_id,
        template_id=template_id,
    )
    if row is None:
        raise _template_not_found()
    object_key = row.object_key
    row.is_default = False
    mark_deleted(row)
    session.commit()
    try:
        get_object_storage().delete(object_key)
    except Exception:
        # The database remains the source of truth; a storage lifecycle rule can
        # safely remove an orphaned object if the backend is temporarily down.
        pass


def default_render_spec(
    session: Session,
    *,
    tenant_id: UUID,
) -> QuoteExcelTemplateRenderSpec | None:
    row = repository.get_default(session, tenant_id=tenant_id)
    if row is None or not row.column_mappings:
        return None
    response = _response(row)
    return QuoteExcelTemplateRenderSpec(
        object_key=row.object_key,
        sheet_name=row.sheet_name,
        header_row=row.header_row,
        data_start_row=row.data_start_row,
        data_end_row=row.data_end_row,
        columns=response.columns,
        column_mappings=response.column_mappings,
    )


def render_spec_for_template(
    session: Session,
    *,
    tenant_id: UUID,
    template_id: UUID | None,
) -> QuoteExcelTemplateRenderSpec | None:
    """Return a tenant-owned render spec, falling back to the default template.

    A quote stores the selected template id so future exports remain stable
    even if the merchant later changes which template is marked as default.
    """
    row = (
        repository.get_for_tenant(
            session,
            tenant_id=tenant_id,
            template_id=template_id,
        )
        if template_id is not None
        else repository.get_default(session, tenant_id=tenant_id)
    )
    if row is None or not row.column_mappings:
        return None
    response = _response(row)
    return QuoteExcelTemplateRenderSpec(
        object_key=row.object_key,
        sheet_name=row.sheet_name,
        header_row=row.header_row,
        data_start_row=row.data_start_row,
        data_end_row=row.data_end_row,
        columns=response.columns,
        column_mappings=response.column_mappings,
    )
