"""Small server-rendered landing pages for public catalog link unfurling.

Only public catalog DTOs enter this renderer: never internal SKU/supplier rows.
No image is downloaded here and no remote URL is fetched on a crawler request.
"""
from __future__ import annotations

from functools import lru_cache
from html import escape, unescape
from html.parser import HTMLParser
from io import BytesIO
import os
from urllib.parse import urlencode, urljoin, urlsplit

from PIL import Image, ImageDraw

from ..catalog_share_schemas import CatalogShareResponse
from ..public_catalog_schemas import PublicProductPage


class _PlainText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str):
        self.parts.append(data)


def plain_text(value: str | None, limit: int = 200) -> str:
    parser = _PlainText()
    parser.feed(value or "")
    return " ".join(unescape(" ".join(parser.parts)).split())[:limit]


def absolute_public_url(value: str | None, origin: str) -> str | None:
    if not value or any(ord(char) < 32 for char in value) or "\\" in value:
        return None
    try:
        result = urljoin(origin.rstrip("/") + "/", value)
        parts = urlsplit(result)
        if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
            return None
        return result
    except ValueError:
        return None


def share_html(share: CatalogShareResponse, page: PublicProductPage, *, origin: str) -> str:
    # Production's configured public origin takes precedence over proxy/Host
    # input. Development uses the browser-facing host preserved by Vite.
    origin = os.getenv("PUBLIC_BASE_URL", "").strip() or origin
    first = page.items[0]
    name = first.name if share.target_type == "PRODUCTS" and page.total == 1 else share.title
    title = plain_text(f"{name} · {share.store_name}", 160)
    description = plain_text(
        first.description if page.total == 1 and first.description
        else " · ".join(item.name for item in page.items),
        240,
    ) or plain_text(share.store_name)
    locale = page.locale or first.locale
    query = urlencode({"lang": locale})
    canonical = absolute_public_url(f"{share.share_path}?{query}", origin)
    store_path = share.share_path.rsplit("/share/", 1)[0]
    # The query form renders the same scoped catalog without re-entering the
    # server preview route. It also retains the child storefront's own slug.
    destination = f"{store_path}?{urlencode({'share': share.id.hex, 'lang': locale})}"
    image = next((url for item in page.items if (url := absolute_public_url(item.image_url, origin))), None)
    image = image or absolute_public_url(share.store_logo_url, origin) or absolute_public_url("/api/catalog-share-placeholder.png", origin)
    # Media is shared catalog data, but a local media URL need not disclose a
    # parent storefront alias. The public media endpoint accepts child aliases.
    if image and urlsplit(image).netloc == urlsplit(origin).netloc:
        parts = urlsplit(image)
        path_parts = parts.path.split("/")
        if len(path_parts) >= 6 and path_parts[1:3] == ["api", "store"] and path_parts[4] == "media":
            path_parts[3] = store_path.lstrip("/")
            image = parts._replace(path="/".join(path_parts)).geturl()

    def meta(key: str, value: str | None, *, attribute: str = "property") -> str:
        return f'<meta {attribute}="{key}" content="{escape(value or "", quote=True)}">'

    metadata = "\n".join([
        meta("description", description, attribute="name"),
        meta("og:type", "website"), meta("og:title", title),
        meta("og:description", description), meta("og:url", canonical),
        meta("og:site_name", plain_text(share.store_name)),
        meta("og:locale", locale.replace("-", "_")),
        meta("og:image", image), meta("og:image:alt", plain_text(name)),
        meta("twitter:card", "summary_large_image", attribute="name"),
        meta("twitter:title", title, attribute="name"),
        meta("twitter:description", description, attribute="name"),
        meta("twitter:image", image, attribute="name"),
        meta("twitter:image:alt", plain_text(name), attribute="name"),
    ])
    return f'''<!doctype html>
<html lang="{escape(locale, quote=True)}" prefix="og: https://ogp.me/ns#">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title>
{metadata}
<link rel="canonical" href="{escape(canonical or '', quote=True)}">
<meta name="robots" content="noindex, follow">
<style>body{{font:16px/1.6 system-ui,sans-serif;background:#f5f7f6;color:#182d27;margin:0;padding:32px}}main{{max-width:640px;margin:5vh auto;background:white;padding:28px;border-radius:20px}}img{{width:100%;max-height:380px;object-fit:contain}}a{{color:#157755}}</style>
<script src="/api/catalog-share-navigation.js" defer></script></head>
<body><main><img src="{escape(image or '', quote=True)}" alt="{escape(plain_text(name), quote=True)}">
<h1>{escape(plain_text(name))}</h1><p>{escape(description)}</p>
<a data-share-target href="{escape(destination, quote=True)}">{escape(plain_text(share.store_name))} →</a>
</main></body></html>'''


@lru_cache(maxsize=1)
def placeholder_image() -> bytes:
    """Neutral raster fallback when neither products nor merchant have a photo."""
    image = Image.new("RGB", (1200, 630), "#edf5f1")
    draw = ImageDraw.Draw(image)
    draw.polygon([(440, 225), (600, 145), (760, 225), (600, 310)], fill="#71b39a")
    draw.polygon([(440, 240), (592, 325), (592, 490), (440, 405)], fill="#459679")
    draw.polygon([(608, 325), (760, 240), (760, 405), (608, 490)], fill="#227457")
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()
