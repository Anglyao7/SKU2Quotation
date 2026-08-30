from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .constants import DEFAULT_TENANT_ID
from .database import Base
from .identity_models import (  # noqa: F401
    AuthRefreshTokenRow,
    AuthSessionRow,
    CustomerAccountAccessEventRow,
    LocalAccountCredentialRow,
    MembershipRoleRow,
    MembershipRow,
    OrganizationRow,
    PermissionRow,
    RolePermissionRow,
    RoleRow,
    TenantRow,
    UserRow,
)
from .image_intelligence_models import (  # noqa: F401
    ImageEmbeddingRow,
    ImageIndexJobRow,
    ImageSearchRow,
    VisionObservationRow,
)
from .model_mixins import AuditTimestampMixin


class SupplierRow(AuditTimestampMixin, Base):
    __tablename__ = "suppliers"
    __table_args__ = (
        CheckConstraint(
            "status IN ('ACTIVE', 'INACTIVE', 'BLOCKED', 'ARCHIVED')",
            name="status_allowed",
        ),
        CheckConstraint(
            "risk_level IN ('LOW', 'MEDIUM', 'HIGH', 'UNKNOWN')",
            name="risk_level_allowed",
        ),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint("active_skus >= 0", name="active_skus_nonnegative"),
        CheckConstraint(
            "country_code IS NULL OR (length(country_code) = 2 AND country_code = UPPER(country_code))",
            name="country_code_format",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_suppliers_tenant_identity"),
        UniqueConstraint("tenant_id", "supplier_code", name="uq_suppliers_tenant_code"),
        Index("ix_suppliers_tenant_status_deleted", "tenant_id", "status", "deleted_at"),
    )

    # Legacy SUP-* primary keys remain during the compatibility migration.
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), default=DEFAULT_TENANT_ID, nullable=False
    )
    supplier_code: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(300), index=True)
    category: Mapped[str] = mapped_column(String(200), default="待分类")
    category_summary: Mapped[str | None] = mapped_column(String(300), nullable=True)
    country_code: Mapped[str | None] = mapped_column(String(2), nullable=True)
    website: Mapped[str | None] = mapped_column(Text, nullable=True)
    contact_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(100), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    whatsapp: Mapped[str | None] = mapped_column(String(100), nullable=True)
    wechat: Mapped[str | None] = mapped_column(String(100), nullable=True)
    country_region: Mapped[str | None] = mapped_column(String(200), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    business_scope: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="ACTIVE", index=True)
    risk_level: Mapped[str] = mapped_column(String(30), default="UNKNOWN", nullable=False)
    version: Mapped[int] = mapped_column(BigInteger, default=1, nullable=False)
    active_skus: Mapped[int] = mapped_column(Integer, default=0)
    health: Mapped[str] = mapped_column(String(30), default="good")


class SourceFileRow(AuditTimestampMixin, Base):
    __tablename__ = "source_files"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_source_files_tenant_identity"),
        ForeignKeyConstraint(
            ["tenant_id", "media_object_id"],
            ["media_objects.tenant_id", "media_objects.id"],
            name="fk_source_files_tenant_media",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "security_status IN ('PENDING_SCAN', 'SCANNING', 'ACCEPTED', "
            "'QUARANTINED', 'REJECTED', 'SCAN_ERROR', 'LEGACY_ACCEPTED')",
            name="security_status_allowed",
        ),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), default=DEFAULT_TENANT_ID, nullable=False
    )
    media_object_id: Mapped[UUID | None] = mapped_column(nullable=True)
    security_status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="LEGACY_ACCEPTED"
    )
    original_filename: Mapped[str] = mapped_column(String(500))
    stored_filename: Mapped[str] = mapped_column(String(500))
    local_path: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    byte_size: Mapped[int] = mapped_column(BigInteger)
    extension: Mapped[str] = mapped_column(String(20), default="")
    detected_type: Mapped[str] = mapped_column(String(80))
    extension_matches: Mapped[bool] = mapped_column(default=True)
    parser: Mapped[str] = mapped_column(String(80))
    warning: Mapped[str | None] = mapped_column(Text, nullable=True)

    jobs: Mapped[list["ImportJobRow"]] = relationship(back_populates="source_file")


class ImportJobRow(AuditTimestampMixin, Base):
    __tablename__ = "import_jobs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_import_jobs_tenant_identity"),
        ForeignKeyConstraint(
            ["tenant_id", "source_file_id"],
            ["source_files.tenant_id", "source_files.id"],
            name="fk_import_jobs_tenant_source_file",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "supplier_id"],
            ["suppliers.tenant_id", "suppliers.id"],
            name="fk_import_jobs_tenant_supplier",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "batch_id"],
            ["catalog_import_batches.tenant_id", "catalog_import_batches.id"],
            name="fk_import_jobs_tenant_batch",
            ondelete="RESTRICT",
        ),
        Index("ix_import_jobs_tenant_batch", "tenant_id", "batch_id"),
        Index("ix_import_jobs_created_at", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), default=DEFAULT_TENANT_ID, nullable=False
    )
    source_file_id: Mapped[str] = mapped_column(String(40), index=True)
    batch_id: Mapped[UUID | None] = mapped_column(nullable=True)
    supplier_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    supplier_name: Mapped[str] = mapped_column(String(200), default="待选择供应商")
    source_type: Mapped[str] = mapped_column(String(40), default="UNKNOWN")
    status: Mapped[str] = mapped_column(String(30), default="parsing", index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    products_count: Mapped[int] = mapped_column(Integer, default=0)
    warnings_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    file_rollback_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    source_file: Mapped[SourceFileRow] = relationship(back_populates="jobs")
    reviews: Mapped[list["ReviewItemRow"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    worker_jobs: Mapped[list["WorkerJobRow"]] = relationship(
        back_populates="import_job"
    )


class ReviewItemRow(AuditTimestampMixin, Base):
    __tablename__ = "review_items"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_review_items_tenant_identity"),
        ForeignKeyConstraint(
            ["tenant_id", "job_id"],
            ["import_jobs.tenant_id", "import_jobs.id"],
            name="fk_review_items_tenant_job",
            ondelete="CASCADE",
        ),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), default=DEFAULT_TENANT_ID, nullable=False
    )
    job_id: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    name: Mapped[str] = mapped_column(String(500), default="待命名产品")
    model: Mapped[str] = mapped_column(String(300), default="")
    category: Mapped[str] = mapped_column(String(300), default="待分类")
    supplier_name: Mapped[str] = mapped_column(String(200), default="待选择供应商")
    source_filename: Mapped[str] = mapped_column(String(500))
    source_location: Mapped[str] = mapped_column(String(300))
    image_status: Mapped[str] = mapped_column(String(30), default="SOURCE")
    fields: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    job: Mapped[ImportJobRow] = relationship(back_populates="reviews")


from .product_supplier_models import (  # noqa: E402,F401
    ProductAttributeRow,
    ProductCategoryRow,
    ProductImageRow,
    ProductRow,
    ProductVersionRow,
    SupplierProductRow,
    SupplierScoreRow,
)

from .ai_data_models import (  # noqa: E402,F401
    AIProviderRouteRow,
    AISourceEvidenceRow,
    AITaskRow,
)

from .knowledge_embedding_models import (  # noqa: E402,F401
    EmbeddingRow,
    KnowledgeChunkRow,
    KnowledgeDocumentRow,
)

from .product_intelligence_models import (  # noqa: E402,F401
    AIRunRow,
    AITaskStepRow,
    InboxEventRow,
    OutboxEventRow,
    ProductCandidateDecisionRow,
    ProductFieldCandidateRow,
)

from .file_security_models import MediaObjectRow, WorkerJobRow  # noqa: E402,F401

from .product_center_models import (  # noqa: E402,F401
    AttributeDefinitionRow,
    ProductAuditEventRow,
    SkuRow,
    SupplierPriceRow,
)

from .subaccount_pricing_models import (  # noqa: E402,F401
    SubaccountCategoryPriceOverrideRow,
    SubaccountPricingPolicyRow,
    SubaccountProductPriceOverrideRow,
    SubaccountSkuPriceOverrideRow,
)

from .trade_flow_models import (  # noqa: E402,F401
    CustomerRow,
    InquiryItemRow,
    InquiryMatchResultRow,
    InquiryRow,
    QuotationApprovalRow,
    QuotationItemRow,
    QuotationRow,
    QuotationVersionRow,
)

from .public_catalog_models import (  # noqa: E402,F401
    CatalogShareRow,
    PublicCatalogOfferRow,
    PublicQuoteDownloadTokenRow,
    PublicQuoteDraftItemRow,
    PublicQuoteDraftRow,
    StorefrontOrderRecordRow,
    TenantPublicProfileRow,
)

from .quote_template_models import QuoteExcelTemplateRow  # noqa: E402,F401

from .inventory_models import (  # noqa: E402,F401
    InventoryBalanceRow,
    InventoryDocumentItemRow,
    InventoryDocumentRow,
    InventoryMovementRow,
    PurchaseOrderItemRow,
    PurchaseOrderRow,
    SalesOrderItemRow,
    SalesOrderRow,
    WarehouseRow,
)

from .tag_models import ProductTagRow  # noqa: E402,F401

from .embedding_management_models import (  # noqa: E402,F401
    EmbeddingProviderSettingsRow,
    ImageEmbeddingProviderSettingsRow,
    KnowledgeIndexJobRow,
    RerankProviderSettingsRow,
)

from .image_generation_models import (  # noqa: E402,F401
    ImageGenerationProviderSettingsRow,
)

from .image_enhancement_models import (  # noqa: E402,F401
    ImageEnhancementItemRow,
    ImageEnhancementTaskRow,
)

from .translation_management_models import (  # noqa: E402,F401
    TranslationProviderSettingsRow,
)

from .support_ai_models import (  # noqa: E402,F401
    SupportAIAgentRow,
    SupportAIEvidenceUseRow,
    SupportAIIngestionJobRow,
    SupportAIKnowledgeBaseRow,
    SupportAIKnowledgeChunkRow,
    SupportAIKnowledgeSourceRow,
    SupportAIProviderSettingsRow,
    SupportAIRunRow,
    SupportAISettingsRow,
    SupportAITrainingCaseRow,
    SupportAITrainingRuleRow,
    SupportAITrainingVersionRow,
)

from .catalog_translation_models import (  # noqa: E402,F401
    CatalogLanguagePackRow,
    CatalogSkuTranslationRow,
    CatalogTextTranslationRow,
    CatalogTranslationBatchAttemptRow,
    CatalogTranslationBatchRow,
    CatalogTranslationJobRow,
)

from .catalog_operation_models import (  # noqa: E402,F401
    CatalogDeleteJobRow,
    CatalogImportBatchRow,
)

from .storefront_analytics_models import (  # noqa: E402,F401
    StorefrontProductViewDailyRow,
    StorefrontProductViewEventRow,
)

from .announcement_models import StorefrontAnnouncementRow  # noqa: E402,F401

from .support_models import (  # noqa: E402,F401
    StorefrontChatConversationRow,
    StorefrontChatMessageRow,
)

from .dashboard_models import DashboardStatisticsRow  # noqa: E402,F401

from .platform_usage_models import (  # noqa: E402,F401
    StorefrontVisitEventRow,
    TenantUsageDailyRow,
)

from .search_analytics_models import (  # noqa: E402,F401
    StorefrontSearchTermDailyRow,
)

from .storefront_page_models import StorefrontCustomPageRow  # noqa: E402,F401
