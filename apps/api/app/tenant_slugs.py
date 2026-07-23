"""Storefront slug names that are owned by the application or its edge.

Tenant storefronts live at ``/{tenant_slug}``, so every static top-level route
must remain unavailable for tenant creation.  Keep this set backend-owned and
verify it against the web router in the architecture tests.
"""

from __future__ import annotations

from typing import Final


RESERVED_TENANT_SLUGS: Final[frozenset[str]] = frozenset(
    {
        # React application routes.
        "ai-search",
        "console",
        "dashboard",
        "inquiries",
        "login",
        "privacy",
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
