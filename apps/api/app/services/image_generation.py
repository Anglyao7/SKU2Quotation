from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping, Sequence

import httpx

from ..model_mixins import utcnow
from .image_generation_configuration import (
    decrypt_api_key,
    get_managed_image_generation_settings,
    image_generation_configuration_snapshot,
)
from .image_generation_rate_limit import image_generation_request_slot


ImageGenerationOutputFormat = Literal["url", "b64_json"]


class ImageGenerationError(ValueError):
    """A safe error raised by the image-to-image provider."""


@dataclass(frozen=True, slots=True)
class ImageEditResult:
    output_format: ImageGenerationOutputFormat
    url: str | None
    b64_json: str | None
    revised_prompt: str | None
    latency_ms: int


def _response_value(payload: object, key: str) -> str | None:
    if not isinstance(payload, Mapping):
        return None
    value = payload.get(key)
    return value if isinstance(value, str) and value.strip() else None


def edit_image(
    session,
    *,
    prompt: str,
    images: Sequence[str],
    size: str = "1024x1024",
    output_format: ImageGenerationOutputFormat = "url",
) -> ImageEditResult:
    """Run Agnes image-to-image editing with URL or Base64 output.

    This deliberately does not expose text-to-image or other workflows. The
    caller chooses the response format per request; the provider config only
    stores the endpoint, model and credentials.
    """

    normalized_prompt = prompt.strip()
    normalized_images = [str(image).strip() for image in images if str(image).strip()]
    if not normalized_prompt:
        raise ImageGenerationError("image editing prompt is required")
    if not normalized_images:
        raise ImageGenerationError("at least one input image is required")
    if len(normalized_images) > 8:
        raise ImageGenerationError("no more than 8 input images are supported")
    if output_format not in {"url", "b64_json"}:
        raise ImageGenerationError("unsupported image output format")

    settings = get_managed_image_generation_settings(session)
    if settings is None:
        snapshot = image_generation_configuration_snapshot(session)
        if not snapshot.enabled or not snapshot.api_key_configured:
            raise ImageGenerationError("image generation provider is not configured")
        raise ImageGenerationError(
            "environment image generation providers cannot be used without a managed key"
        )
    if not settings.is_active:
        raise ImageGenerationError("image generation provider is disabled")
    api_key = decrypt_api_key(settings.api_key_ciphertext)
    payload = {
        "model": settings.model_name,
        "prompt": normalized_prompt,
        "size": size,
        "extra_body": {
            "image": normalized_images,
            "response_format": output_format,
        },
    }
    started = utcnow()
    try:
        with image_generation_request_slot(
            requests_per_minute=settings.requests_per_minute,
            concurrency_limit=settings.concurrency_limit,
            timeout_seconds=settings.timeout_seconds,
        ):
            response = httpx.post(
                settings.base_url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=float(settings.timeout_seconds),
            )
            response.raise_for_status()
            body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise ImageGenerationError(
            "image generation provider request failed"
        ) from exc
    data = body.get("data") if isinstance(body, Mapping) else None
    first = data[0] if isinstance(data, list) and data else None
    if not isinstance(first, Mapping):
        raise ImageGenerationError("image generation provider returned no image")
    url = _response_value(first, "url")
    b64_json = _response_value(first, "b64_json")
    if output_format == "url" and not url:
        raise ImageGenerationError("image generation provider returned no URL")
    if output_format == "b64_json" and not b64_json:
        raise ImageGenerationError("image generation provider returned no Base64 image")
    elapsed = max(0, int((utcnow() - started).total_seconds() * 1000))
    return ImageEditResult(
        output_format=output_format,
        url=url,
        b64_json=b64_json,
        revised_prompt=_response_value(first, "revised_prompt"),
        latency_ms=elapsed,
    )
