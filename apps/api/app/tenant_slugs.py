"""Storefront slug names that are owned by the application or its edge.

Tenant storefronts live at ``/{tenant_slug}``, so every static top-level route
must remain unavailable for tenant creation.  Keep this set backend-owned and
verify it against the web router in the architecture tests.
"""

from __future__ import annotations

import unicodedata
from typing import Final


RESERVED_TENANT_SLUGS: Final[frozenset[str]] = frozenset(
    {
        # React application routes.
        "account",
        "ai-search",
        "console",
        "dashboard",
        "inquiries",
        "inventory",
        "login",
        "privacy",
        "portal",
        "products",
        "quotations",
        "review",
        "store",
        "suppliers",
        "system",
        # Public edge and static asset namespaces.
        "api",
        "assets",
        "healthz",
    }
)


def is_reserved_tenant_slug(value: str) -> bool:
    """Return whether a normalized storefront path belongs to the platform."""

    return value.strip().lower() in RESERVED_TENANT_SLUGS


def storefront_slug_from_name(value: str) -> str:
    """Build a readable, URL-safe storefront path from a merchant name.

    Unicode letters and numbers are preserved so Chinese merchant names remain
    recognizable in the browser. Whitespace and punctuation become a single
    hyphen, while application-owned routes receive a safe suffix.
    """

    normalized = unicodedata.normalize("NFKC", value).strip().casefold()
    parts: list[str] = []
    pending_separator = False
    for character in normalized:
        if character.isalnum():
            if pending_separator and parts:
                parts.append("-")
            parts.append(character)
            pending_separator = False
        else:
            pending_separator = bool(parts)
    slug = "".join(parts).strip("-")[:80].rstrip("-")
    if not slug:
        raise ValueError("merchant name must contain at least one letter or number")
    if is_reserved_tenant_slug(slug):
        suffix = "-store"
        slug = f"{slug[: 80 - len(suffix)].rstrip('-')}{suffix}"
    return slug
