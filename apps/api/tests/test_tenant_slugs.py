import pytest

from app.tenant_slugs import storefront_slug_from_name


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
