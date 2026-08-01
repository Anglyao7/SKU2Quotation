from __future__ import annotations

from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


AnnouncementDisplayType = Literal["TICKER", "MODAL"]
AnnouncementStatus = Literal["DRAFT", "PUBLISHED", "PAUSED"]
AnnouncementBlockType = Literal[
    "heading",
    "paragraph",
    "bullet_list",
    "image",
    "video",
    "link",
]


class AnnouncementContentBlock(BaseModel):
    type: AnnouncementBlockType
    text: str | None = Field(default=None, max_length=10_000)
    url: str | None = Field(default=None, max_length=2_000)
    alt: str | None = Field(default=None, max_length=300)
    caption: str | None = Field(default=None, max_length=500)

    @field_validator("text", "url", "alt", "caption", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def validate_content(self) -> "AnnouncementContentBlock":
        text_types = {"heading", "paragraph", "bullet_list"}
        if self.type in text_types and not self.text:
            raise ValueError(f"{self.type} block requires text")
        if self.type == "link" and (not self.text or not self.url):
            raise ValueError("link block requires text and URL")
        if self.type in {"image", "video"} and not self.url:
            raise ValueError(f"{self.type} block requires URL")
        if self.url:
            parsed = urlsplit(self.url)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.netloc
                or parsed.username is not None
                or parsed.password is not None
            ):
                raise ValueError("media and link URLs must use HTTP or HTTPS")
        return self


class AnnouncementWriteRequest(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    display_type: AnnouncementDisplayType
    ticker_text: str | None = Field(default=None, max_length=2_000)
    content_blocks: list[AnnouncementContentBlock] = Field(
        default_factory=list,
        max_length=50,
    )
    starts_at: datetime
    ends_at: datetime | None = None
    duration_days: int | None = Field(default=None, ge=1, le=365)
    ticker_speed_px_per_second: int = Field(default=60, ge=20, le=160)
    publication_status: AnnouncementStatus = "DRAFT"
    related_sku_ids: list[UUID] = Field(default_factory=list, max_length=20)

    @field_validator("title", "ticker_text", mode="before")
    @classmethod
    def normalize_text(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        normalized = value.strip()
        return normalized or None

    @field_validator("related_sku_ids")
    @classmethod
    def unique_related_skus(cls, value: list[UUID]) -> list[UUID]:
        return list(dict.fromkeys(value))

    @model_validator(mode="after")
    def validate_announcement(self) -> "AnnouncementWriteRequest":
        if (self.ends_at is None) == (self.duration_days is None):
            raise ValueError("provide exactly one of ends_at or duration_days")
        if self.ends_at is not None and self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be later than starts_at")
        if self.display_type == "TICKER":
            if not self.ticker_text:
                raise ValueError("ticker announcements require plain text")
            if self.content_blocks:
                raise ValueError("ticker announcements do not support rich content")
        else:
            if self.ticker_text:
                raise ValueError("modal announcements use content blocks")
            if not self.content_blocks:
                raise ValueError("modal announcements require content blocks")
        return self


class AnnouncementRelatedSkuResponse(BaseModel):
    id: UUID
    product_id: UUID
    sku_code: str
    name: str
    product_name: str
    is_public: bool


class AnnouncementResponse(BaseModel):
    id: UUID
    title: str | None
    display_type: AnnouncementDisplayType
    ticker_text: str | None
    content_blocks: list[AnnouncementContentBlock]
    starts_at: datetime
    ends_at: datetime
    ticker_speed_px_per_second: int
    publication_status: AnnouncementStatus
    related_skus: list[AnnouncementRelatedSkuResponse] = Field(default_factory=list)
    version: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class AnnouncementListResponse(BaseModel):
    items: list[AnnouncementResponse]
    total: int


class PublicAnnouncementResponse(BaseModel):
    id: UUID
    title: str | None
    display_type: AnnouncementDisplayType
    ticker_text: str | None
    content_blocks: list[AnnouncementContentBlock]
    starts_at: datetime
    ends_at: datetime
    ticker_speed_px_per_second: int
    version: int
    related_skus: list[AnnouncementRelatedSkuResponse] = Field(default_factory=list)
