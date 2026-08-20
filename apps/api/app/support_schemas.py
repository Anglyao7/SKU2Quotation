from __future__ import annotations

from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from .storefront_locales import StorefrontLocale, normalize_storefront_locale


SupportConversationStatus = Literal["OPEN", "CLOSED"]
SupportSenderType = Literal["VISITOR", "MERCHANT", "SYSTEM", "AI"]
SupportAutomationState = Literal["AI_ACTIVE", "HUMAN_TAKEOVER"]
SupportHumanAssistanceState = Literal["NONE", "OFFERED", "REQUESTED", "RESOLVED"]


def _safe_image_url(value: str | None) -> str | None:
    normalized = (value or "").strip()
    if not normalized:
        return None
    parsed = urlsplit(normalized)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("图片链接必须使用 http:// 或 https://")
    return normalized


class SupportCustomActionWrite(BaseModel):
    slot: Literal[2, 3]
    visible: bool = False
    label: str | None = Field(default=None, max_length=40)
    external_image_url: str | None = Field(default=None, max_length=2_000)

    @field_validator("label", mode="before")
    @classmethod
    def normalize_label(cls, value: object) -> object:
        return value.strip() or None if isinstance(value, str) else value

    @field_validator("external_image_url", mode="before")
    @classmethod
    def validate_image_url(cls, value: object) -> object:
        if value is None or isinstance(value, str):
            return _safe_image_url(value)
        return value


class SupportCustomActionResponse(SupportCustomActionWrite):
    image_url: str | None = None
    has_uploaded_image: bool = False


class SupportSettingsUpdate(BaseModel):
    welcome_message: str = Field(min_length=1, max_length=500)
    custom_actions: list[SupportCustomActionWrite] = Field(
        default_factory=list,
        max_length=2,
    )

    @field_validator("welcome_message", mode="before")
    @classmethod
    def normalize_welcome(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def unique_slots(self) -> "SupportSettingsUpdate":
        slots = [row.slot for row in self.custom_actions]
        if len(slots) != len(set(slots)):
            raise ValueError("每个悬浮球只能配置一次")
        return self


class SupportSettingsResponse(BaseModel):
    welcome_message: str
    custom_actions: list[SupportCustomActionResponse]


class PublicSupportWidgetResponse(BaseModel):
    enabled: bool = True
    title: str = "AI 智能客服"
    welcome_message: str
    ai_enabled: bool = False
    custom_actions: list[SupportCustomActionResponse]


class PublicChatMessageWrite(BaseModel):
    message: str = Field(min_length=1, max_length=4_000)
    client_message_id: str | None = Field(default=None, max_length=80)
    locale: StorefrontLocale | None = None

    @field_validator("message", mode="before")
    @classmethod
    def normalize_message(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("locale", mode="before")
    @classmethod
    def normalize_locale(cls, value: object) -> object:
        if value is None:
            return None
        locale = normalize_storefront_locale(str(value))
        if locale is None:
            raise ValueError("请选择系统支持的客服语言")
        return locale


class PublicChatConversationCreate(PublicChatMessageWrite):
    visitor_name: str | None = Field(default=None, max_length=120)
    visitor_email: str | None = Field(default=None, max_length=320)
    locale: StorefrontLocale = "zh-CN"

    @field_validator("visitor_name", mode="before")
    @classmethod
    def normalize_visitor_name(cls, value: object) -> object:
        return value.strip() or None if isinstance(value, str) else value

    @field_validator("visitor_email", mode="before")
    @classmethod
    def normalize_visitor_email(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        normalized = value.strip().casefold()
        if normalized and ("@" not in normalized or normalized.startswith("@")):
            raise ValueError("请输入有效的邮箱地址")
        return normalized or None


class SupportCitationResponse(BaseModel):
    citation_number: int = Field(ge=1)
    source_type: Literal["SKU", "FILE"]
    source_entity_id: str
    source_title: str
    source_version: int = Field(ge=1)
    classification: Literal["PUBLIC", "CUSTOMER_APPROVED"]
    locator: dict[str, object] = Field(default_factory=dict)
    excerpt: str
    score: float = Field(ge=0, le=1)


class PublicSupportChatMessageResponse(BaseModel):
    id: UUID
    sender_type: SupportSenderType
    body: str
    created_at: datetime
    citations: list[SupportCitationResponse] = Field(default_factory=list)


SupportTranslationStatus = Literal[
    "PENDING",
    "READY",
    "FAILED",
    "UNAVAILABLE",
    "NOT_REQUIRED",
]


class SupportChatMessageResponse(PublicSupportChatMessageResponse):
    draft_body: str | None = None
    translated_body: str | None = None
    translation_source_locale: str | None = None
    translation_target_locale: str | None = None
    translation_status: SupportTranslationStatus = "PENDING"


class PublicChatConversationResponse(BaseModel):
    id: UUID
    reference_number: str
    status: SupportConversationStatus
    messages: list[PublicSupportChatMessageResponse]
    access_token: str | None = None
    automation_state: SupportAutomationState = "AI_ACTIVE"
    ai_processing: bool = False
    human_assistance_state: SupportHumanAssistanceState = "NONE"
    human_assistance_requested_at: datetime | None = None


class SupportConversationSummaryResponse(BaseModel):
    id: UUID
    reference_number: str
    visitor_name: str | None
    visitor_email: str | None
    visitor_country_code: str | None = None
    visitor_timezone: str | None = None
    locale: str
    status: SupportConversationStatus
    last_message_preview: str
    last_message_at: datetime
    unread: bool
    automation_state: SupportAutomationState = "AI_ACTIVE"
    ai_processing: bool = False
    human_assistance_state: SupportHumanAssistanceState = "NONE"
    human_assistance_requested_at: datetime | None = None


class SupportConversationDetailResponse(SupportConversationSummaryResponse):
    messages: list[SupportChatMessageResponse]


class SupportConversationPageResponse(BaseModel):
    items: list[SupportConversationSummaryResponse]
    total: int
    page: int
    page_size: int
    pages: int


class SupportHumanRequestResponse(BaseModel):
    conversation_id: UUID
    reference_number: str
    visitor_name: str | None
    visitor_email: str | None
    locale: str
    message_preview: str
    requested_at: datetime


class SupportHumanRequestSummaryResponse(BaseModel):
    pending_count: int = Field(ge=0)
    items: list[SupportHumanRequestResponse]


class SupportMerchantMessageWrite(BaseModel):
    message: str = Field(min_length=1, max_length=4_000)
    draft_message: str | None = Field(default=None, max_length=4_000)
    source_locale: StorefrontLocale | None = None
    target_locale: StorefrontLocale | None = None

    @field_validator("message", mode="before")
    @classmethod
    def normalize_message(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("draft_message", mode="before")
    @classmethod
    def normalize_draft_message(cls, value: object) -> object:
        return value.strip() or None if isinstance(value, str) else value

    @model_validator(mode="after")
    def complete_translation_metadata(self) -> "SupportMerchantMessageWrite":
        values = (self.draft_message, self.source_locale, self.target_locale)
        if any(value is not None for value in values) and not all(
            value is not None for value in values
        ):
            raise ValueError("译文发送需要完整的原文和语言信息")
        return self


class SupportTranslationPreviewWrite(BaseModel):
    message: str = Field(min_length=1, max_length=4_000)
    target_locale: StorefrontLocale

    @field_validator("message", mode="before")
    @classmethod
    def normalize_message(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class SupportTranslationPreviewResponse(BaseModel):
    source_locale: StorefrontLocale
    target_locale: StorefrontLocale
    original_message: str
    translated_message: str


class SupportConversationStatusUpdate(BaseModel):
    status: SupportConversationStatus


class SupportConversationAutomationUpdate(BaseModel):
    automation_state: SupportAutomationState
