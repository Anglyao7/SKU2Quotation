from html.parser import HTMLParser
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.catalog_share_schemas import CatalogShareCreate
from app.services.catalog_share_metadata import absolute_public_url, share_html, placeholder_image


class Metadata(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.tags = {}
        self.links = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "meta":
            self.tags[values.get("property", values.get("name"))] = values.get("content")
        if tag == "a":
            self.links.append(values.get("href"))


def data():
    share = SimpleNamespace(
        id=uuid4(), target_type="PRODUCTS", title="Stale title", store_name='Reseller "Alice"',
        share_path="/alice/share/12345678", store_logo_url=None,
    )
    product = SimpleNamespace(name='New <b>pet bowl</b> " &', description='Nice <b>bowl</b> & washable',
                              image_url="https://resources.example.test/bowl.jpg?v=2&x=3", locale="en-US")
    return share, SimpleNamespace(items=[product], total=1, locale="en-US")


def test_metadata_is_server_readable_and_scoped(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://shop.example.test")
    share, page = data()
    html = share_html(share, page, origin="http://internal:8000")
    tags = Metadata(html)
    assert tags.tags['og:title'] == 'New pet bowl " & · Reseller "Alice"'
    assert tags.tags['og:description'] == 'Nice bowl & washable'
    assert tags.tags['og:image'] == page.items[0].image_url
    assert tags.tags['og:url'] == 'https://shop.example.test/alice/share/12345678?lang=en-US'
    assert tags.tags['og:locale'] == 'en_US'
    assert tags.tags['twitter:card'] == 'summary_large_image'
    assert tags.links == [f'/alice?share={share.id.hex}&lang=en-US']
    assert "internal:8000" not in html
    assert "Stale title" not in html
    assert '<script src="/api/catalog-share-navigation.js" defer>' in html


@pytest.mark.parametrize("value", ['javascript:alert(1)', 'data:text/html,x', 'https://user:secret@example.com/a', 'https://[invalid', '/x\n.jpg', '//x\\evil/y'])
def test_unsafe_image_urls_are_rejected(value):
    assert absolute_public_url(value, 'https://shop.example.test') is None


def test_category_and_image_fallback(monkeypatch):
    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
    share, page = data()
    share.target_type = "CATEGORY"
    share.title = "Pet bowls"
    page.items[0].image_url = 'javascript:alert(1)'
    tags = Metadata(share_html(share, page, origin="http://localhost:5173"))
    assert tags.tags['og:title'].startswith('Pet bowls')
    assert tags.tags['og:image'] == 'http://localhost:5173/api/catalog-share-placeholder.png'
    assert placeholder_image().startswith(b'\x89PNG\r\n\x1a\n')


def test_local_media_uses_child_alias(monkeypatch):
    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
    share, page = data()
    page.items[0].image_url = '/api/store/parent/media/123?v=9'
    tags = Metadata(share_html(share, page, origin="https://shop.example.test"))
    assert tags.tags['og:image'] == 'https://shop.example.test/api/store/alice/media/123?v=9'


def test_metadata_escapes_attribute_injection(monkeypatch):
    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
    share, page = data()
    page.items[0].name = '\"><script>alert(1)</script>'
    page.items[0].image_url = 'https://cdn.example.test/a" onerror="alert(1)'
    html = share_html(share, page, origin="https://shop.example.test")
    assert '<script>alert(1)</script>' not in html
    assert ' onerror="' not in html


def test_product_shares_keep_legacy_sku_support_but_reject_mixed_targets():
    product = uuid4()
    assert CatalogShareCreate(target_type="PRODUCTS", product_ids=[product]).product_ids == [product]
    assert CatalogShareCreate(target_type="PRODUCTS", sku_ids=[product]).sku_ids == [product]
    for payload in ({}, {"product_ids": [product, product]}, {"product_ids": [product], "sku_ids": [uuid4()]}, {"product_ids": [product], "category_id": uuid4()}):
        with pytest.raises(ValidationError):
            CatalogShareCreate(target_type="PRODUCTS", **payload)
