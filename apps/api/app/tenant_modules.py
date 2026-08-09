from __future__ import annotations

from collections.abc import Iterable
from typing import Final, Literal, TypeAlias


TenantModuleCode: TypeAlias = Literal[
    "products",
    "analytics",
    "inventory",
    "announcements",
    "support",
    "support_ai",
    "inquiries",
    "quotations",
    "subaccounts",
]


TENANT_MODULE_CODES: Final[tuple[TenantModuleCode, ...]] = (
    "products",
    "analytics",
    "inventory",
    "announcements",
    "support",
    "support_ai",
    "inquiries",
    "quotations",
    "subaccounts",
)

# Permission rows remain the fine-grained authorization source for merchant
# members.  Tenant modules are the platform-level ceiling: a role can grant an
# action only when the corresponding module is enabled for that merchant.
# System permissions are internal account safeguards rather than a merchant
# feature module, so they remain available to the roles that already own them.
PERMISSION_MODULE_TO_TENANT_MODULE: Final[dict[str, TenantModuleCode]] = {
    "product": "products",
    "supplier": "products",
    "catalog": "products",
    "analytics": "analytics",
    "inventory": "inventory",
    "announcement": "announcements",
    "support": "support",
    "support_ai": "support_ai",
    "knowledge": "support_ai",
    "customer": "inquiries",
    "inquiry": "inquiries",
    "quotation": "quotations",
    "order": "quotations",
    "customer_portal": "subaccounts",
}

ALWAYS_ENABLED_PERMISSION_MODULES: Final[frozenset[str]] = frozenset({"system"})


def default_tenant_modules() -> list[TenantModuleCode]:
    return list(TENANT_MODULE_CODES)


def normalized_tenant_modules(value: object) -> tuple[TenantModuleCode, ...]:
    """Return canonical module order while preserving legacy full access."""

    if value is None:
        return TENANT_MODULE_CODES
    if not isinstance(value, (list, tuple, set, frozenset)):
        return TENANT_MODULE_CODES
    selected = {str(item) for item in value}
    return tuple(code for code in TENANT_MODULE_CODES if code in selected)


def enabled_permission_modules(
    value: object,
) -> frozenset[str]:
    selected = frozenset(normalized_tenant_modules(value))
    return ALWAYS_ENABLED_PERMISSION_MODULES | frozenset(
        permission_module
        for permission_module, tenant_module in PERMISSION_MODULE_TO_TENANT_MODULE.items()
        if tenant_module in selected
    )


def canonical_tenant_module_list(
    value: Iterable[str],
) -> list[TenantModuleCode]:
    selected = set(value)
    return [code for code in TENANT_MODULE_CODES if code in selected]
