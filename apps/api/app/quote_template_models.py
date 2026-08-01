from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .ai_data_models import JSON_DOCUMENT
from .database import Base
from .model_mixins import AuditTimestampMixin


class QuoteExcelTemplateRow(AuditTimestampMixin, Base):
    """Tenant-owned Excel layout and column mapping for public quotations."""

    __tablename__ = "quote_excel_templates"
    __table_args__ = (
        CheckConstraint("byte_size > 0", name="byte_size_positive"),
        CheckConstraint("length(sha256) = 64", name="sha256_length"),
        CheckConstraint("header_row >= 1", name="header_row_positive"),
        CheckConstraint("data_start_row > header_row", name="data_start_after_header"),
        CheckConstraint("data_end_row >= data_start_row", name="data_end_after_start"),
        CheckConstraint("version >= 1", name="version_positive"),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="uq_quote_excel_templates_tenant_identity",
        ),
        Index(
            "ix_quote_excel_templates_tenant_default",
            "tenant_id",
            "is_default",
            "updated_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    object_key: Mapped[str] = mapped_column(String(1000), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sheet_names: Mapped[list[str]] = mapped_column(
        JSON_DOCUMENT,
        default=list,
        nullable=False,
    )
    sheet_name: Mapped[str] = mapped_column(String(200), nullable=False)
    header_row: Mapped[int] = mapped_column(Integer, nullable=False)
    data_start_row: Mapped[int] = mapped_column(Integer, nullable=False)
    data_end_row: Mapped[int] = mapped_column(Integer, nullable=False)
    columns: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON_DOCUMENT,
        default=list,
        nullable=False,
    )
    column_mappings: Mapped[dict[str, str]] = mapped_column(
        JSON_DOCUMENT,
        default=dict,
        nullable=False,
    )
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    version: Mapped[int] = mapped_column(BigInteger, default=1, nullable=False)
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    updated_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
