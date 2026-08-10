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

MerchantIdentityCode: TypeAlias = Literal["ADMIN", "USER"]
TenantModuleAccessMode: TypeAlias = Literal["INHERIT", "CUSTOM"]

MERCHANT_IDENTITY_CODES: Final[tuple[MerchantIdentityCode, ...]] = (
    "ADMIN",
    "USER",
)
DEFAULT_MERCHANT_IDENTITY: Final[MerchantIdentityCode] = "USER"
DEFAULT_TENANT_MODULE_ACCESS_MODE: Final[TenantModuleAccessMode] = "INHERIT"


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


def default_merchant_identity_modules(
    _identity_code: MerchantIdentityCode = DEFAULT_MERCHANT_IDENTITY,
) -> list[TenantModuleCode]:
    """Start both identities without removing access from existing merchants.

    Platform administrators can subsequently tune each identity template from
    the merchant management screen.  Sensitive platform APIs still require
    the server-owned ``is_platform_admin`` flag and are never granted here.
    """

    return default_tenant_modules()


def normalized_merchant_identity(value: object) -> MerchantIdentityCode:
    normalized = str(value or DEFAULT_MERCHANT_IDENTITY).strip().upper()
    if normalized == "ADMIN":
        return "ADMIN"
    return "USER"


def normalized_module_access_mode(value: object) -> TenantModuleAccessMode:
    normalized = str(value or DEFAULT_TENANT_MODULE_ACCESS_MODE).strip().upper()
    if normalized == "CUSTOM":
        return "CUSTOM"
    return "INHERIT"


def normalized_tenant_modules(value: object) -> tuple[TenantModuleCode, ...]:
    """Return canonical module order while preserving legacy full access."""

    if value is None:
        return TENANT_MODULE_CODES
    if not isinstance(value, (list, tuple, set, frozenset)):
        return TENANT_MODULE_CODES
    selected = {str(item) for item in value}
    return tuple(code for code in TENANT_MODULE_CODES if code in selected)


def effective_tenant_modules(
    *,
    identity_code: object,
    access_mode: object,
    custom_modules: object,
    identity_default_modules: object | None = None,
) -> tuple[TenantModuleCode, ...]:
    if normalized_module_access_mode(access_mode) == "CUSTOM":
        return normalized_tenant_modules(custom_modules)
    defaults = (
        identity_default_modules
        if identity_default_modules is not None
        else default_merchant_identity_modules(
            normalized_merchant_identity(identity_code)
        )
    )
    return normalized_tenant_modules(defaults)


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
