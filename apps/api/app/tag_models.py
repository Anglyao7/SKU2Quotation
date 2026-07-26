from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base
from .model_mixins import utcnow


class ProductTagRow(Base):
    """产品标签字典表 - 租户级别统一管理"""

    __tablename__ = "product_tags"
    __table_args__ = (
        Index("idx_product_tags_tenant_name", "tenant_id", "normalized_name"),
        UniqueConstraint("tenant_id", "normalized_name", name="uq_product_tags_tenant_normalized_name"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False, comment="标签显示名称")
    normalized_name: Mapped[str] = mapped_column(
        String(80), nullable=False, comment="标签规范化名称（小写）用于去重"
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True, comment="标签说明")
    category: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="标签分类：状态/特性/场景/优势等"
    )
    usage_count: Mapped[int] = mapped_column(default=0, nullable=False, comment="使用次数")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    def __repr__(self) -> str:
        return f"<ProductTag {self.name}>"
