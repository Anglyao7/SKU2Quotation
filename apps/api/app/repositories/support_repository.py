from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from ..support_models import (
    StorefrontChatConversationRow,
    StorefrontChatMessageRow,
)


def get_conversation(
    session: Session,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
) -> StorefrontChatConversationRow | None:
    return session.scalar(
        select(StorefrontChatConversationRow).where(
            StorefrontChatConversationRow.tenant_id == tenant_id,
            StorefrontChatConversationRow.id == conversation_id,
        )
    )


def get_conversation_for_update(
    session: Session,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
) -> StorefrontChatConversationRow | None:
    return session.scalar(
        select(StorefrontChatConversationRow)
        .where(
            StorefrontChatConversationRow.tenant_id == tenant_id,
            StorefrontChatConversationRow.id == conversation_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def get_conversation_by_token_hash(
    session: Session,
    *,
    tenant_id: UUID,
    token_hash: str,
) -> StorefrontChatConversationRow | None:
    return session.scalar(
        select(StorefrontChatConversationRow).where(
            StorefrontChatConversationRow.tenant_id == tenant_id,
            StorefrontChatConversationRow.visitor_token_hash == token_hash,
        )
    )


def list_messages(
    session: Session,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
) -> list[StorefrontChatMessageRow]:
    return list(
        session.scalars(
            select(StorefrontChatMessageRow)
            .where(
                StorefrontChatMessageRow.tenant_id == tenant_id,
                StorefrontChatMessageRow.conversation_id == conversation_id,
            )
            .order_by(
                StorefrontChatMessageRow.created_at,
                StorefrontChatMessageRow.id,
            )
        ).all()
    )


def find_client_message(
    session: Session,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
    client_message_id: str | None,
) -> StorefrontChatMessageRow | None:
    if not client_message_id:
        return None
    return session.scalar(
        select(StorefrontChatMessageRow).where(
            StorefrontChatMessageRow.tenant_id == tenant_id,
            StorefrontChatMessageRow.conversation_id == conversation_id,
            StorefrontChatMessageRow.client_message_id == client_message_id,
        )
    )


def list_conversations(
    session: Session,
    *,
    tenant_id: UUID,
    page: int,
    page_size: int,
    status: str | None,
    query: str,
    preview_locale: str,
) -> tuple[list[tuple[StorefrontChatConversationRow, str]], int]:
    predicate = [StorefrontChatConversationRow.tenant_id == tenant_id]
    if status:
        predicate.append(StorefrontChatConversationRow.status == status)
    normalized = query.strip()
    if normalized:
        pattern = f"%{normalized}%"
        predicate.append(
            or_(
                StorefrontChatConversationRow.reference_number.ilike(pattern),
                StorefrontChatConversationRow.visitor_name.ilike(pattern),
                StorefrontChatConversationRow.visitor_email.ilike(pattern),
            )
        )
    total = int(
        session.scalar(
            select(func.count(StorefrontChatConversationRow.id)).where(*predicate)
        )
        or 0
    )
    latest_body = (
        select(
            case(
                (
                    (
                        StorefrontChatMessageRow.translation_status == "READY"
                    )
                    & (
                        StorefrontChatMessageRow.translation_target_locale
                        == preview_locale
                    )
                    & StorefrontChatMessageRow.translated_body.is_not(None),
                    StorefrontChatMessageRow.translated_body,
                ),
                else_=StorefrontChatMessageRow.body,
            )
        )
        .where(
            StorefrontChatMessageRow.tenant_id
            == StorefrontChatConversationRow.tenant_id,
            StorefrontChatMessageRow.conversation_id
            == StorefrontChatConversationRow.id,
        )
        .order_by(
            StorefrontChatMessageRow.created_at.desc(),
            StorefrontChatMessageRow.id.desc(),
        )
        .limit(1)
        .scalar_subquery()
    )
    rows = session.execute(
        select(StorefrontChatConversationRow, latest_body)
        .where(*predicate)
        .order_by(StorefrontChatConversationRow.last_message_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return [(row, str(preview or "")) for row, preview in rows], total


def list_pending_human_requests(
    session: Session,
    *,
    tenant_id: UUID,
    limit: int,
) -> tuple[list[tuple[StorefrontChatConversationRow, str]], int]:
    predicate = (
        StorefrontChatConversationRow.tenant_id == tenant_id,
        StorefrontChatConversationRow.status == "OPEN",
        StorefrontChatConversationRow.human_requested_at.is_not(None),
        StorefrontChatConversationRow.human_resolved_at.is_(None),
    )
    total = int(
        session.scalar(
            select(func.count(StorefrontChatConversationRow.id)).where(*predicate)
        )
        or 0
    )
    latest_visitor_body = (
        select(StorefrontChatMessageRow.body)
        .where(
            StorefrontChatMessageRow.tenant_id
            == StorefrontChatConversationRow.tenant_id,
            StorefrontChatMessageRow.conversation_id
            == StorefrontChatConversationRow.id,
            StorefrontChatMessageRow.sender_type == "VISITOR",
        )
        .order_by(
            StorefrontChatMessageRow.created_at.desc(),
            StorefrontChatMessageRow.id.desc(),
        )
        .limit(1)
        .scalar_subquery()
    )
    rows = session.execute(
        select(StorefrontChatConversationRow, latest_visitor_body)
        .where(*predicate)
        .order_by(StorefrontChatConversationRow.human_requested_at.desc())
        .limit(limit)
    ).all()
    return [(row, str(preview or "")) for row, preview in rows], total


def has_unread_visitor_message(
    conversation: StorefrontChatConversationRow,
) -> bool:
    visitor_at = conversation.last_visitor_message_at
    if visitor_at is None:
        return False
    read_at: datetime | None = conversation.merchant_last_read_at
    if read_at is None:
        return True
    if visitor_at.tzinfo is None:
        visitor_at = visitor_at.replace(tzinfo=UTC)
    if read_at.tzinfo is None:
        read_at = read_at.replace(tzinfo=UTC)
    return visitor_at > read_at
