from __future__ import annotations

import pytest

from app.services.storage import MAX_UPLOAD_BYTES, upload_size_limit_bytes


def test_compact_and_standard_profiles_share_the_large_upload_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    minimum_supported_size = 50 * 1024 * 1024

    monkeypatch.setenv("ATC_RUNTIME_PROFILE", "compact")
    assert upload_size_limit_bytes() == MAX_UPLOAD_BYTES
    assert upload_size_limit_bytes() >= minimum_supported_size

    monkeypatch.setenv("ATC_RUNTIME_PROFILE", "standard")
    assert upload_size_limit_bytes() == MAX_UPLOAD_BYTES
