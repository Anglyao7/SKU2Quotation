import pytest

from app.tenant_slugs import storefront_slug_from_name, unique_storefront_slug


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
