from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, ValidationError, field_validator


MAX_STOREFRONT_FOOTER_SECTIONS = 4
MAX_STOREFRONT_FOOTER_LINKS_PER_SECTION = 8
_PUBLIC_LINK_SCHEMES = frozenset({"http", "https", "mailto", "tel"})


def _normalize_public_link(value: object, *, optional: bool) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str):
        raise ValueError("footer link must be a string")
    normalized = value.strip()
    if not normalized:
        if optional:
            return None
        raise ValueError("footer link must not be blank")
    if len(normalized) > 2_000:
        raise ValueError("footer link is too long")
    if any(ord(character) < 32 or ord(character) == 127 for character in normalized):
        raise ValueError("footer link contains control characters")
    if normalized.startswith("/"):
        if normalized.startswith("//") or "\\" in normalized:
            raise ValueError("footer link must use a safe relative path")
        return normalized

    parsed = urlsplit(normalized)
    scheme = parsed.scheme.casefold()
    if scheme not in _PUBLIC_LINK_SCHEMES:
        raise ValueError("footer link protocol is not supported")
    if scheme in {"http", "https"} and not parsed.hostname:
        raise ValueError("footer website link must include a host")
    if scheme in {"mailto", "tel"} and not parsed.path:
        raise ValueError("footer contact link must include a destination")
    return normalized


class StorefrontFooterLink(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    url: str = Field(min_length=1, max_length=2_000)

    @field_validator("label", mode="before")
    @classmethod
    def normalize_label(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("url", mode="before")
    @classmethod
    def normalize_url(cls, value: object) -> object:
        return _normalize_public_link(value, optional=False)


class StorefrontFooterSection(BaseModel):
    title: str = Field(min_length=1, max_length=80)
    title_url: str | None = Field(default=None, max_length=2_000)
    links: list[StorefrontFooterLink] = Field(
        default_factory=list,
        max_length=MAX_STOREFRONT_FOOTER_LINKS_PER_SECTION,
    )

    @field_validator("title", mode="before")
    @classmethod
    def normalize_title(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("title_url", mode="before")
    @classmethod
    def normalize_title_url(cls, value: object) -> object:
        return _normalize_public_link(value, optional=True)


def default_storefront_footer_sections(
    *,
    merchant_name: str,
    contact_email: str | None,
) -> list[StorefrontFooterSection]:
    sections = [
        StorefrontFooterSection(
            title=f"About {merchant_name}",
            links=[StorefrontFooterLink(label="Privacy Policy", url="/privacy")],
        )
    ]
    normalized_email = (contact_email or "").strip()
    if normalized_email:
        sections.append(
            StorefrontFooterSection(
                title="Contact Us",
                links=[
                    StorefrontFooterLink(
                        label="Email",
                        url=f"mailto:{normalized_email}",
                    )
                ],
            )
        )
    return sections


def storefront_footer_sections(
    value: object,
    *,
    merchant_name: str,
    contact_email: str | None,
) -> list[StorefrontFooterSection]:
    if not isinstance(value, dict) or "sections" not in value:
        return default_storefront_footer_sections(
            merchant_name=merchant_name,
            contact_email=contact_email,
        )
    raw_sections = value.get("sections")
    if not isinstance(raw_sections, list):
        return default_storefront_footer_sections(
            merchant_name=merchant_name,
            contact_email=contact_email,
        )

    sections: list[StorefrontFooterSection] = []
    for raw_section in raw_sections[:MAX_STOREFRONT_FOOTER_SECTIONS]:
        try:
            sections.append(StorefrontFooterSection.model_validate(raw_section))
        except ValidationError:
            continue
    return sections


def storefront_footer_config(
    sections: list[StorefrontFooterSection],
) -> dict[str, Any]:
    return {
        "sections": [section.model_dump(mode="json") for section in sections],
    }

