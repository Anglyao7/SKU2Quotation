import pytest
from uuid import UUID

from app.tenant_slugs import (
    storefront_slug_from_name,
    subaccount_storefront_slug_base,
    unique_storefront_slug,
)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("澄湾选品", "澄湾选品"),
        ("  Acme Trading Co., Ltd.  ", "acme-trading-co-ltd"),
        ("海岸 家居", "海岸-家居"),
        ("Login", "login-store"),
    ],
)
def test_storefront_slug_follows_merchant_name(name: str, expected: str) -> None:
    assert storefront_slug_from_name(name) == expected


def test_storefront_slug_rejects_names_without_letters_or_numbers() -> None:
    with pytest.raises(ValueError):
        storefront_slug_from_name(" ·—— ")


def test_unique_storefront_slug_uses_readable_numeric_suffixes() -> None:
    base = "yoyo"
    assert unique_storefront_slug(base, set()) == "yoyo"
    assert unique_storefront_slug(base, {"yoyo"}) == "yoyo-2"
    assert unique_storefront_slug(base, {"YOYO", "yoyo-2"}) == "yoyo-3"


def test_unique_storefront_slug_keeps_numbered_path_within_limit() -> None:
    base = "a" * 80
    candidate = unique_storefront_slug(base, {base})
    assert candidate.endswith("-2")
    assert len(candidate) == 80


def test_subaccount_storefront_slug_uses_email_shaped_login_local_part() -> None:
    assert subaccount_storefront_slug_base(
        login_identifier="AAA@Example.com",
        display_name="Customer Name",
    ) == "aaa"


def test_subaccount_storefront_slug_keeps_login_name_over_contact_email() -> None:
    assert subaccount_storefront_slug_base(
        login_identifier="aaa",
        email="contact@example.com",
        display_name="Customer Name",
    ) == "aaa"


def test_subaccount_storefront_slug_falls_back_to_login_identifier() -> None:
    assert subaccount_storefront_slug_base(
        login_identifier="Sales Team / East",
        display_name="Customer Name",
    ) == "sales-team-east"


def test_customer_subaccount_uses_its_independent_short_storefront_path() -> None:
    from app.services.storefront_paths import membership_storefront_path

    membership_id = UUID("11111111-1111-4111-8111-111111111111")
    assert membership_storefront_path(
        account_scope="CUSTOMER_SUBACCOUNT",
        membership_id=membership_id,
        tenant_slug="main-merchant",
        storefront_slug="aaa",
    ) == "/aaa"


def test_customer_subaccount_never_falls_back_to_the_merchant_storefront() -> None:
    from app.services.storefront_paths import membership_storefront_path

    membership_id = UUID("11111111-1111-4111-8111-111111111111")
    expected = "/main-merchant/account/account--11111111-1111-4111-8111-111111111111"
    assert membership_storefront_path(
        account_scope="CUSTOMER_SUBACCOUNT",
        membership_id=membership_id,
        tenant_slug="main-merchant",
        storefront_slug=None,
    ) == expected
    assert membership_storefront_path(
        account_scope="CUSTOMER_SUBACCOUNT",
        membership_id=membership_id,
        tenant_slug="main-merchant",
        storefront_slug="main-merchant",
    ) == expected


def test_staff_keeps_the_merchant_storefront_path() -> None:
    from app.services.storefront_paths import membership_storefront_path

    assert membership_storefront_path(
        account_scope="STAFF",
        membership_id=UUID("11111111-1111-4111-8111-111111111111"),
        tenant_slug="main-merchant",
        storefront_slug=None,
    ) == "/main-merchant"
