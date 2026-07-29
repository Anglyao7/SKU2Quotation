"""Safe primitives for migrating externally hosted catalog images.

This module deliberately contains no database logic.  The one-off migration
command can therefore download and validate untrusted remote files before it
changes any authoritative product-image row.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import ipaddress
from pathlib import Path, PurePosixPath
import socket
import struct
from typing import Callable, Iterable
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from ..ports.object_storage import ObjectStoragePort


_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_JPEG_START_OF_FRAME_MARKERS = frozenset(
    {
        0xC0,
        0xC1,
        0xC2,
        0xC3,
        0xC5,
        0xC6,
        0xC7,
        0xC9,
        0xCA,
        0xCB,
        0xCD,
        0xCE,
        0xCF,
    }
)
_MEDIA_EXTENSIONS = {
    "image/avif": "avif",
    "image/bmp": "bmp",
    "image/gif": "gif",
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}


class ImageMigrationError(RuntimeError):
    """A stable, non-secret failure code suitable for operator logs."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class SourcePolicy:
    allowed_hosts: tuple[str, ...]
    allow_all_public_hosts: bool = False
    allow_private_hosts: bool = False

    def __post_init__(self) -> None:
        normalized = tuple(
            sorted({_normalize_host_pattern(value) for value in self.allowed_hosts})
        )
        object.__setattr__(self, "allowed_hosts", normalized)


@dataclass(frozen=True, slots=True)
class ImageFileMetadata:
    content_type: str
    extension: str
    byte_size: int
    sha256: str
    width: int | None
    height: int | None
    final_url: str


Resolver = Callable[..., Iterable[tuple[object, object, object, object, tuple[object, ...]]]]


def _normalize_hostname(value: str) -> str:
    normalized = value.strip().rstrip(".").casefold()
    if not normalized:
        raise ImageMigrationError("SOURCE_HOST_INVALID")
    try:
        return normalized.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ImageMigrationError("SOURCE_HOST_INVALID") from exc


def _normalize_host_pattern(value: str) -> str:
    candidate = value.strip()
    if candidate.startswith("*."):
        return f"*.{_normalize_hostname(candidate[2:])}"
    return _normalize_hostname(candidate)


def host_matches_patterns(host: str, patterns: Iterable[str]) -> bool:
    normalized_host = _normalize_hostname(host)
    for raw_pattern in patterns:
        pattern = _normalize_host_pattern(raw_pattern)
        if pattern.startswith("*."):
            root = pattern[2:]
            if normalized_host == root or normalized_host.endswith(f".{root}"):
                return True
        elif normalized_host == pattern:
            return True
    return False


def source_hostname(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme.casefold() not in {"http", "https"} or parsed.hostname is None:
        raise ImageMigrationError("SOURCE_URL_INVALID")
    return _normalize_hostname(parsed.hostname)


def redacted_source_url(url: str) -> str:
    """Keep host/path useful to operators without logging signed query values."""

    parsed = urlsplit(url)
    hostname = parsed.hostname or ""
    if not hostname:
        return "<invalid-url>"
    host = hostname
    try:
        port = parsed.port
    except ValueError:
        port = None
    if port is not None:
        host = f"{host}:{port}"
    return urlunsplit((parsed.scheme, host, parsed.path, "", ""))


def validate_source_url(
    url: str,
    *,
    policy: SourcePolicy,
    resolver: Resolver = socket.getaddrinfo,
) -> str:
    parsed = urlsplit(url)
    scheme = parsed.scheme.casefold()
    if scheme not in {"http", "https"}:
        raise ImageMigrationError("SOURCE_SCHEME_NOT_ALLOWED")
    if parsed.username is not None or parsed.password is not None:
        raise ImageMigrationError("SOURCE_USERINFO_NOT_ALLOWED")
    if parsed.hostname is None:
        raise ImageMigrationError("SOURCE_HOST_INVALID")
    try:
        port = parsed.port or (443 if scheme == "https" else 80)
    except ValueError as exc:
        raise ImageMigrationError("SOURCE_PORT_INVALID") from exc

    hostname = _normalize_hostname(parsed.hostname)
    if not policy.allow_all_public_hosts and not host_matches_patterns(
        hostname, policy.allowed_hosts
    ):
        raise ImageMigrationError("SOURCE_HOST_NOT_ALLOWED")

    if not policy.allow_private_hosts:
        try:
            addresses = tuple(
                resolver(hostname, port, type=socket.SOCK_STREAM)
            )
        except OSError as exc:
            raise ImageMigrationError("SOURCE_DNS_FAILED") from exc
        if not addresses:
            raise ImageMigrationError("SOURCE_DNS_FAILED")
        for address in addresses:
            try:
                resolved = ipaddress.ip_address(str(address[4][0]))
            except (IndexError, TypeError, ValueError) as exc:
                raise ImageMigrationError("SOURCE_DNS_INVALID") from exc
            if not resolved.is_global:
                raise ImageMigrationError("SOURCE_ADDRESS_NOT_PUBLIC")
    return url


def _detect_content_type(header: bytes) -> str:
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if header.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if header.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if (
        len(header) >= 12
        and header.startswith(b"RIFF")
        and header[8:12] == b"WEBP"
    ):
        return "image/webp"
    if header.startswith(b"BM"):
        return "image/bmp"
    if (
        len(header) >= 16
        and header[4:8] == b"ftyp"
        and any(brand in {b"avif", b"avis"} for brand in (header[8:12], header[16:20]))
    ):
        return "image/avif"
    raise ImageMigrationError("IMAGE_FORMAT_UNSUPPORTED")


def _jpeg_dimensions(path: Path) -> tuple[int | None, int | None]:
    with path.open("rb") as source:
        if source.read(2) != b"\xff\xd8":
            return None, None
        while True:
            marker_prefix = source.read(1)
            if not marker_prefix:
                return None, None
            if marker_prefix != b"\xff":
                continue
            marker = source.read(1)
            while marker == b"\xff":
                marker = source.read(1)
            if not marker:
                return None, None
            marker_value = marker[0]
            if marker_value in {0x01, 0xD8, 0xD9} or 0xD0 <= marker_value <= 0xD7:
                continue
            raw_length = source.read(2)
            if len(raw_length) != 2:
                return None, None
            segment_length = struct.unpack(">H", raw_length)[0]
            if segment_length < 2:
                return None, None
            if marker_value in _JPEG_START_OF_FRAME_MARKERS:
                payload = source.read(5)
                if len(payload) != 5:
                    return None, None
                height, width = struct.unpack(">HH", payload[1:5])
                return width or None, height or None
            source.seek(segment_length - 2, 1)


def _webp_dimensions(header: bytes) -> tuple[int | None, int | None]:
    if len(header) < 30:
        return None, None
    chunk = header[12:16]
    if chunk == b"VP8X" and len(header) >= 30:
        width = 1 + int.from_bytes(header[24:27], "little")
        height = 1 + int.from_bytes(header[27:30], "little")
        return width, height
    if chunk == b"VP8L" and len(header) >= 25 and header[20] == 0x2F:
        b0, b1, b2, b3 = header[21:25]
        width = 1 + b0 + ((b1 & 0x3F) << 8)
        height = 1 + ((b1 & 0xC0) >> 6) + (b2 << 2) + ((b3 & 0x0F) << 10)
        return width, height
    if chunk == b"VP8 ":
        frame_start = header.find(b"\x9d\x01\x2a", 20)
        if frame_start >= 0 and len(header) >= frame_start + 7:
            width, height = struct.unpack(
                "<HH", header[frame_start + 3 : frame_start + 7]
            )
            return width & 0x3FFF, height & 0x3FFF
    return None, None


def image_dimensions(
    path: Path, *, content_type: str
) -> tuple[int | None, int | None]:
    with path.open("rb") as source:
        header = source.read(64)
    if content_type == "image/png" and len(header) >= 24:
        return struct.unpack(">II", header[16:24])
    if content_type == "image/gif" and len(header) >= 10:
        return struct.unpack("<HH", header[6:10])
    if content_type == "image/jpeg":
        return _jpeg_dimensions(path)
    if content_type == "image/webp":
        return _webp_dimensions(header)
    if content_type == "image/bmp" and len(header) >= 26:
        width, height = struct.unpack("<ii", header[18:26])
        return abs(width) or None, abs(height) or None
    return None, None


def inspect_image_file(
    path: Path,
    *,
    final_url: str,
    sha256: str | None = None,
    max_pixels: int = 100_000_000,
) -> ImageFileMetadata:
    byte_size = path.stat().st_size
    if byte_size <= 0:
        raise ImageMigrationError("IMAGE_EMPTY")
    with path.open("rb") as source:
        header = source.read(64)
    content_type = _detect_content_type(header)
    width, height = image_dimensions(path, content_type=content_type)
    if width is not None and height is not None:
        if width <= 0 or height <= 0:
            raise ImageMigrationError("IMAGE_DIMENSIONS_INVALID")
        if width * height > max_pixels:
            raise ImageMigrationError("IMAGE_PIXEL_LIMIT_EXCEEDED")
    content_hash = sha256
    if content_hash is None:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
        content_hash = digest.hexdigest()
    return ImageFileMetadata(
        content_type=content_type,
        extension=_MEDIA_EXTENSIONS[content_type],
        byte_size=byte_size,
        sha256=content_hash,
        width=width,
        height=height,
        final_url=final_url,
    )


def download_image(
    client: httpx.Client,
    *,
    source_url: str,
    destination: Path,
    policy: SourcePolicy,
    max_bytes: int,
    max_pixels: int,
    max_redirects: int,
    resolver: Resolver = socket.getaddrinfo,
) -> ImageFileMetadata:
    current_url = source_url
    destination.unlink(missing_ok=True)
    try:
        for redirect_count in range(max_redirects + 1):
            validate_source_url(current_url, policy=policy, resolver=resolver)
            try:
                request = client.build_request(
                    "GET",
                    current_url,
                    headers={
                        "Accept": (
                            "image/avif,image/webp,image/png,image/jpeg,"
                            "image/gif,image/bmp;q=0.9,*/*;q=0.1"
                        ),
                        "User-Agent": "AITradeCloud-Image-Migrator/1.0",
                    },
                )
                response_context = client.stream(
                    request.method,
                    request.url,
                    headers=request.headers,
                    follow_redirects=False,
                )
                with response_context as response:
                    if response.status_code in _REDIRECT_STATUSES:
                        location = response.headers.get("location")
                        if not location:
                            raise ImageMigrationError("SOURCE_REDIRECT_INVALID")
                        if redirect_count >= max_redirects:
                            raise ImageMigrationError("SOURCE_REDIRECT_LIMIT")
                        current_url = urljoin(str(response.url), location)
                        continue
                    if response.status_code != 200:
                        raise ImageMigrationError(
                            f"SOURCE_HTTP_{response.status_code}"
                        )
                    raw_length = response.headers.get("content-length")
                    if raw_length:
                        try:
                            declared_length = int(raw_length)
                        except ValueError:
                            declared_length = 0
                        if declared_length > max_bytes:
                            raise ImageMigrationError("IMAGE_SIZE_LIMIT_EXCEEDED")
                    digest = hashlib.sha256()
                    total = 0
                    with destination.open("wb") as output:
                        for chunk in response.iter_bytes(1024 * 1024):
                            if not chunk:
                                continue
                            total += len(chunk)
                            if total > max_bytes:
                                raise ImageMigrationError(
                                    "IMAGE_SIZE_LIMIT_EXCEEDED"
                                )
                            digest.update(chunk)
                            output.write(chunk)
            except ImageMigrationError:
                raise
            except httpx.TimeoutException as exc:
                raise ImageMigrationError("SOURCE_TIMEOUT") from exc
            except httpx.HTTPError as exc:
                raise ImageMigrationError("SOURCE_NETWORK_ERROR") from exc
            return inspect_image_file(
                destination,
                final_url=current_url,
                sha256=digest.hexdigest(),
                max_pixels=max_pixels,
            )
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    destination.unlink(missing_ok=True)
    raise ImageMigrationError("SOURCE_REDIRECT_LIMIT")


def build_catalog_object_key(
    *,
    tenant_id: str,
    product_id: str,
    image_id: str,
    content_sha256: str,
    extension: str,
) -> str:
    if len(content_sha256) != 64 or any(
        character not in "0123456789abcdef" for character in content_sha256
    ):
        raise ValueError("content_sha256 must be a lowercase SHA-256 digest")
    if extension not in set(_MEDIA_EXTENSIONS.values()):
        raise ValueError("unsupported image extension")
    key = PurePosixPath(
        "tenants",
        tenant_id,
        "catalog",
        "products",
        product_id,
        "images",
        image_id,
        f"{content_sha256}.{extension}",
    )
    if key.is_absolute() or ".." in key.parts:
        raise ValueError("unsafe object key")
    return key.as_posix()


def ensure_object_uploaded(
    storage: ObjectStoragePort,
    *,
    source: Path,
    object_key: str,
    content_type: str,
    expected_sha256: str,
) -> bool:
    """Upload once and verify any pre-existing deterministic destination.

    Returns ``True`` when a new object was uploaded and ``False`` when an
    identical object was already present from an interrupted earlier run.
    """

    if storage.exists(object_key):
        digest = hashlib.sha256()
        with storage.materialize(object_key) as existing:
            with existing.open("rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
        if digest.hexdigest() != expected_sha256:
            raise ImageMigrationError("TARGET_OBJECT_HASH_MISMATCH")
        return False
    storage.put_file(source, object_key=object_key, content_type=content_type)
    return True
