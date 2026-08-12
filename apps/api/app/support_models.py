from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base
from .model_mixins import AuditTimestampMixin


class StorefrontChatConversationRow(AuditTimestampMixin, Base):
    __tablename__ = "storefront_chat_conversations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('OPEN', 'CLOSED')",
            name="status_allowed",
        ),
        CheckConstraint(
            "automation_state IN ('AI_ACTIVE', 'HUMAN_TAKEOVER')",
            name="automation_state_allowed",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="uq_storefront_chat_conversations_tenant_identity",
        ),
        UniqueConstraint(
            "tenant_id",
            "reference_number",
            name="uq_storefront_chat_conversations_reference",
        ),
        UniqueConstraint(
            "visitor_token_hash",
            name="uq_storefront_chat_conversations_visitor_token",
        ),
        Index(
            "ix_storefront_chat_conversations_tenant_activity",
            "tenant_id",
            "status",
            "last_message_at",
        ),
        Index(
            "ix_storefront_chat_conversations_tenant_human_request",
            "tenant_id",
            "human_requested_at",
            "human_resolved_at",
            "status",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    reference_number: Mapped[str] = mapped_column(String(40), nullable=False)
    visitor_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    visitor_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    visitor_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    locale: Mapped[str] = mapped_column(String(20), default="zh-CN", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="OPEN", nullable=False)
    merchant_last_read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_message_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    last_visitor_message_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_merchant_message_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    automation_state: Mapped[str] = mapped_column(
        String(30), default="AI_ACTIVE", nullable=False
    )
    automation_state_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    human_handoff_offered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    human_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    human_resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    human_request_reason: Mapped[str | None] = mapped_column(
        String(80), nullable=True
    )


class StorefrontChatMessageRow(AuditTimestampMixin, Base):
    __tablename__ = "storefront_chat_messages"
    __table_args__ = (
        CheckConstraint(
            "sender_type IN ('VISITOR', 'MERCHANT', 'SYSTEM', 'AI')",
            name="sender_type_allowed",
        ),
        CheckConstraint(
            "translation_status IN "
            "('PENDING', 'READY', 'FAILED', 'UNAVAILABLE', 'NOT_REQUIRED')",
            name="translation_status_allowed",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="uq_storefront_chat_messages_tenant_identity",
        ),
        UniqueConstraint(
            "tenant_id",
            "conversation_id",
            "client_message_id",
            name="uq_storefront_chat_messages_client_identity",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "conversation_id"],
            [
                "storefront_chat_conversations.tenant_id",
                "storefront_chat_conversations.id",
            ],
            name="fk_storefront_chat_messages_tenant_conversation",
            ondelete="CASCADE",
        ),
        Index(
            "ix_storefront_chat_messages_conversation_created",
            "tenant_id",
            "conversation_id",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    conversation_id: Mapped[UUID] = mapped_column(nullable=False)
    sender_type: Mapped[str] = mapped_column(String(20), nullable=False)
    sender_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    client_message_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    draft_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    translated_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    translation_source_locale: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
    )
    translation_target_locale: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
    )
    translation_status: Mapped[str] = mapped_column(
        String(20),
        default="PENDING",
        nullable=False,
    )
