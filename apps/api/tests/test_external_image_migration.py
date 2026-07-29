from __future__ import annotations

import hashlib
from pathlib import Path
import socket

import httpx
import pytest

from app.services.external_image_migration import (
    ImageMigrationError,
    SourcePolicy,
    build_catalog_object_key,
    download_image,
    ensure_object_uploaded,
    redacted_source_url,
    validate_source_url,
)


PUBLIC_DNS = [
    (
        socket.AF_INET,
        socket.SOCK_STREAM,
        socket.IPPROTO_TCP,
        "",
        ("93.184.216.34", 443),
    )
]
PRIVATE_DNS = [
    (
        socket.AF_INET,
        socket.SOCK_STREAM,
        socket.IPPROTO_TCP,
        "",
        ("127.0.0.1", 80),
    )
]
PNG_2X3 = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x02"
    b"\x00\x00\x00\x03"
    b"\x08\x06\x00\x00\x00"
)


def _resolver(
    rows: list[tuple[object, object, object, object, tuple[object, ...]]],
):
    def resolve(*_args: object, **_kwargs: object):
        return rows

    return resolve


def test_source_policy_requires_allowlisted_public_host() -> None:
    policy = SourcePolicy(allowed_hosts=("images.example.com",))
    assert (
        validate_source_url(
            "https://images.example.com/a.png?signature=secret",
            policy=policy,
            resolver=_resolver(PUBLIC_DNS),
        )
        == "https://images.example.com/a.png?signature=secret"
    )
    with pytest.raises(ImageMigrationError, match="SOURCE_HOST_NOT_ALLOWED"):
        validate_source_url(
            "https://other.example.com/a.png",
            policy=policy,
            resolver=_resolver(PUBLIC_DNS),
        )


def test_source_policy_rejects_private_resolution_and_url_credentials() -> None:
    policy = SourcePolicy(allowed_hosts=("localhost", "images.example.com"))
    with pytest.raises(ImageMigrationError, match="SOURCE_ADDRESS_NOT_PUBLIC"):
        validate_source_url(
            "http://localhost/a.png",
            policy=policy,
            resolver=_resolver(PRIVATE_DNS),
        )
    with pytest.raises(ImageMigrationError, match="SOURCE_USERINFO_NOT_ALLOWED"):
        validate_source_url(
            "https://user:password@images.example.com/a.png",
            policy=policy,
            resolver=_resolver(PUBLIC_DNS),
        )


def test_download_validates_redirect_host_and_image_magic(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "images.example.com":
            return httpx.Response(
                302,
                headers={"location": "https://cdn.example.com/final.png"},
                request=request,
            )
        return httpx.Response(
            200,
            content=PNG_2X3,
            headers={"content-type": "application/octet-stream"},
            request=request,
        )

    policy = SourcePolicy(
        allowed_hosts=("images.example.com", "cdn.example.com")
    )
    destination = tmp_path / "download.bin"
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        metadata = download_image(
            client,
            source_url="https://images.example.com/source",
            destination=destination,
            policy=policy,
            max_bytes=1024,
            max_pixels=100,
            max_redirects=2,
            resolver=_resolver(PUBLIC_DNS),
        )
    assert metadata.content_type == "image/png"
    assert metadata.extension == "png"
    assert metadata.width == 2
    assert metadata.height == 3
    assert metadata.sha256 == hashlib.sha256(PNG_2X3).hexdigest()
    assert metadata.final_url == "https://cdn.example.com/final.png"


def test_download_rejects_non_image_payload(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>not an image</html>", request=request)

    destination = tmp_path / "download.bin"
    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as client,
        pytest.raises(ImageMigrationError, match="IMAGE_FORMAT_UNSUPPORTED"),
    ):
        download_image(
            client,
            source_url="https://images.example.com/source",
            destination=destination,
            policy=SourcePolicy(allowed_hosts=("images.example.com",)),
            max_bytes=1024,
            max_pixels=100,
            max_redirects=0,
            resolver=_resolver(PUBLIC_DNS),
        )
    assert not destination.exists()


def test_object_key_is_deterministic_and_query_is_redacted() -> None:
    digest = "a" * 64
    assert build_catalog_object_key(
        tenant_id="tenant-id",
        product_id="product-id",
        image_id="image-id",
        content_sha256=digest,
        extension="jpg",
    ) == (
        "tenants/tenant-id/catalog/products/product-id/images/"
        f"image-id/{digest}.jpg"
    )
    assert redacted_source_url(
        "https://images.example.com/a.jpg?token=do-not-log"
    ) == "https://images.example.com/a.jpg"


class _MemoryStorage:
    backend_name = "memory"

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def exists(self, object_key: str) -> bool:
        return object_key in self.objects

    def put_file(
        self, source: Path, *, object_key: str, content_type: str | None
    ) -> None:
        del content_type
        self.objects[object_key] = source.read_bytes()

    def materialize(self, object_key: str):
        class Context:
            def __enter__(inner_self):
                inner_self.path = Path(source_path)
                inner_self.path.write_bytes(self.objects[object_key])
                return inner_self.path

            def __exit__(inner_self, *_args: object) -> None:
                inner_self.path.unlink(missing_ok=True)

        source_path = Path(self._temporary_path)
        return Context()

    _temporary_path = ""


def test_existing_target_is_hash_verified(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    source.write_bytes(PNG_2X3)
    storage = _MemoryStorage()
    storage._temporary_path = str(tmp_path / "materialized.png")
    digest = hashlib.sha256(PNG_2X3).hexdigest()
    assert ensure_object_uploaded(
        storage,
        source=source,
        object_key="managed/a.png",
        content_type="image/png",
        expected_sha256=digest,
    )
    assert not ensure_object_uploaded(
        storage,
        source=source,
        object_key="managed/a.png",
        content_type="image/png",
        expected_sha256=digest,
    )
    storage.objects["managed/a.png"] = b"different"
    with pytest.raises(ImageMigrationError, match="TARGET_OBJECT_HASH_MISMATCH"):
        ensure_object_uploaded(
            storage,
            source=source,
            object_key="managed/a.png",
            content_type="image/png",
            expected_sha256=digest,
        )
