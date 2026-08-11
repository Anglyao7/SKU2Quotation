"""Storefront branding helpers shared by merchant and public catalog flows."""

from __future__ import annotations

import io
import os
from urllib.parse import quote

from PIL import Image, ImageOps, UnidentifiedImageError


MAX_MERCHANT_LOGO_BYTES = max(
    1024 * 1024,
    min(int(os.getenv("MAX_MERCHANT_LOGO_BYTES", str(5 * 1024 * 1024))), 20 * 1024 * 1024),
)
MAX_MERCHANT_LOGO_EDGE = 1200


class InvalidStorefrontLogo(ValueError):
    """Raised when uploaded bytes cannot be normalized as a safe image."""


def normalize_storefront_logo(content: bytes) -> bytes:
    """Validate and normalize a merchant logo to a bounded WebP asset."""

    try:
        with Image.open(io.BytesIO(content)) as source:
            source.verify()
        with Image.open(io.BytesIO(content)) as source:
            image = ImageOps.exif_transpose(source)
            image.load()
            image.thumbnail(
                (MAX_MERCHANT_LOGO_EDGE, MAX_MERCHANT_LOGO_EDGE),
                Image.Resampling.LANCZOS,
            )
            has_alpha = "A" in image.getbands() or (
                image.mode == "P" and "transparency" in image.info
            )
            normalized = image.convert("RGBA" if has_alpha else "RGB")
            output = io.BytesIO()
            normalized.save(output, format="WEBP", quality=92, method=4)
            return output.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise InvalidStorefrontLogo("logo image cannot be decoded") from exc


def storefront_logo_url(profile: object | None) -> str | None:
    """Return the public URL for the current logo, preserving legacy URL assets."""

    if profile is None:
        return None
    object_key = str(getattr(profile, "logo_object_key", None) or "").strip()
    if not object_key:
        legacy_url = str(getattr(profile, "logo_url", None) or "").strip()
        return legacy_url or None

    slug = str(getattr(profile, "slug", "") or "").strip()
    if not slug:
        return None
    updated_at = getattr(profile, "updated_at", None)
    version = (
        str(int(updated_at.timestamp()))
        if updated_at is not None and hasattr(updated_at, "timestamp")
        else object_key.rsplit("/", 1)[-1].split(".", 1)[0]
    )
    return f"/api/store/{quote(slug, safe='')}/logo?v={quote(version, safe='')}"
