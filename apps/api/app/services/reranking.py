from __future__ import annotations

import base64
import hashlib
import math
import os
import re
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken
import httpx
from sqlalchemy.orm import Session

from ..embedding_management_models import RerankProviderSettingsRow
from ..model_mixins import utcnow


SETTINGS_ID = "SUPPORT_AI_RERANK"
MIN_TIMEOUT_MS = 100
MAX_TIMEOUT_MS = 800
MIN_DOCUMENTS = 5
MAX_DOCUMENTS = 30


class RerankProviderError(ValueError):
    """Safe rerank failure that never exposes credentials or response bodies."""


def _bounded_environment_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return min(maximum, max(minimum, value))


@dataclass(frozen=True, slots=True)
class RerankResult:
    index: int
    relevance_score: float


@dataclass(frozen=True, slots=True)
class RerankConfigurationSnapshot:
    source: str
    provider: str
    enabled: bool
    base_url: str | None
    model_name: str | None
    timeout_ms: int
    max_documents: int
    api_key_configured: bool
    api_key_hint: str | None
    updated_at: datetime | None


def rerank_endpoint(base_url: str) -> str:
    normalized = base_url.strip().rstrip("/")
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RerankProviderError("rerank base URL must be an HTTP(S) URL")
    if parsed.username is not None or parsed.password is not None:
        raise RerankProviderError("rerank base URL must not contain credentials")
    if normalized.endswith("/rerank"):
        return normalized
    if re.search(r"/v\d+$", normalized, flags=re.IGNORECASE):
        return f"{normalized}/rerank"
    return f"{normalized}/v1/rerank"


class CohereCompatibleReranker:
    """Small adapter for the common ``/v1/rerank`` and ``/v2/rerank`` contract."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model_name: str,
        timeout_ms: int,
        max_documents: int,
        client: httpx.Client | None = None,
    ) -> None:
        if not api_key.strip():
            raise RerankProviderError("rerank API key is required")
        if not model_name.strip():
            raise RerankProviderError("rerank model is required")
        if timeout_ms < MIN_TIMEOUT_MS or timeout_ms > MAX_TIMEOUT_MS:
            raise RerankProviderError("rerank timeout must be between 100 and 800 ms")
        if max_documents < MIN_DOCUMENTS or max_documents > MAX_DOCUMENTS:
            raise RerankProviderError("rerank max documents must be between 5 and 30")
        self.endpoint = rerank_endpoint(base_url)
        self.model_name = model_name.strip()
        self.timeout_ms = timeout_ms
        self.max_documents = max_documents
        self._api_key = api_key.strip()
        self._client = client or httpx.Client()

    def rerank(
        self,
        *,
        query: str,
        documents: list[str],
        top_n: int,
    ) -> list[RerankResult]:
        bounded_documents = documents[: self.max_documents]
        if not query.strip() or not bounded_documents:
            return []
        try:
            response = self._client.post(
                self.endpoint,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model_name,
                    "query": query,
                    "documents": bounded_documents,
                    "top_n": min(max(1, top_n), len(bounded_documents)),
                },
                timeout=self.timeout_ms / 1000,
            )
        except httpx.TimeoutException as exc:
            raise RerankProviderError("rerank provider request timed out") from exc
        except httpx.HTTPError as exc:
            raise RerankProviderError("rerank provider request failed") from exc
        if response.status_code < 200 or response.status_code >= 300:
            raise RerankProviderError(
                f"rerank provider returned HTTP {response.status_code}"
            )
        try:
            payload = response.json()
            raw_results = payload.get("results") or payload.get("data") or []
            results: list[RerankResult] = []
            seen: set[int] = set()
            for item in raw_results:
                index = int(item["index"])
                score = float(
                    item.get("relevance_score", item.get("score", 0.0))
                )
                if (
                    index in seen
                    or index < 0
                    or index >= len(bounded_documents)
                    or not math.isfinite(score)
                ):
                    continue
                seen.add(index)
                results.append(RerankResult(index=index, relevance_score=score))
            if not results:
                raise ValueError("empty rerank result")
            return results
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise RerankProviderError(
                "rerank provider returned an invalid response"
            ) from exc


@lru_cache(maxsize=8)
def _cached_reranker(
    api_key: str,
    base_url: str,
    model_name: str,
    timeout_ms: int,
    max_documents: int,
) -> CohereCompatibleReranker:
    return CohereCompatibleReranker(
        api_key=api_key,
        base_url=base_url,
        model_name=model_name,
        timeout_ms=timeout_ms,
        max_documents=max_documents,
    )


def _master_secret() -> str:
    configured = os.getenv("RERANK_SETTINGS_MASTER_KEY", "").strip()
    secret = configured or os.getenv("AUTH_TOKEN_PEPPER", "").strip()
    managed = os.getenv("APP_ENV", "development").strip().lower() in {
        "production",
        "staging",
    }
    if configured and managed and len(configured) < 32:
        raise RerankProviderError(
            "rerank settings encryption key must contain at least 32 characters"
        )
    if secret:
        return secret
    if managed:
        raise RerankProviderError(
            "rerank settings encryption key is not configured"
        )
    return "local-development-only-rerank-settings-key"


def _fernet() -> Fernet:
    material = hashlib.sha256(
        f"atc:rerank-settings:v1:{_master_secret()}".encode("utf-8")
    ).digest()
    return Fernet(base64.urlsafe_b64encode(material))


def encrypt_api_key(api_key: str) -> str:
    normalized = api_key.strip()
    if not normalized:
        raise RerankProviderError("rerank API key is required")
    return _fernet().encrypt(normalized.encode("utf-8")).decode("ascii")


def decrypt_api_key(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeDecodeError, ValueError) as exc:
        raise RerankProviderError(
            "stored rerank API key cannot be decrypted"
        ) from exc


def get_managed_rerank_settings(
    session: Session,
) -> RerankProviderSettingsRow | None:
    return session.get(RerankProviderSettingsRow, SETTINGS_ID)


def rerank_configuration_snapshot(session: Session) -> RerankConfigurationSnapshot:
    settings = get_managed_rerank_settings(session)
    if settings is not None:
        return RerankConfigurationSnapshot(
            source="database",
            provider=settings.provider,
            enabled=bool(settings.is_active),
            base_url=settings.base_url,
            model_name=settings.model_name,
            timeout_ms=settings.timeout_ms,
            max_documents=settings.max_documents,
            api_key_configured=bool(settings.api_key_ciphertext),
            api_key_hint=(
                f"••••{settings.api_key_last_four}"
                if settings.api_key_last_four
                else None
            ),
            updated_at=settings.updated_at,
        )
    api_key = os.getenv("SUPPORT_AI_RERANK_API_KEY", "").strip()
    base_url = os.getenv("SUPPORT_AI_RERANK_BASE_URL", "").strip()
    model_name = os.getenv("SUPPORT_AI_RERANK_MODEL", "").strip()
    enabled = bool(api_key and base_url and model_name)
    return RerankConfigurationSnapshot(
        source="environment" if enabled else "disabled",
        provider="cohere-compatible",
        enabled=enabled,
        base_url=base_url or None,
        model_name=model_name or None,
        timeout_ms=_bounded_environment_int(
            "SUPPORT_AI_RERANK_TIMEOUT_MS", 800, MIN_TIMEOUT_MS, MAX_TIMEOUT_MS
        ),
        max_documents=_bounded_environment_int(
            "SUPPORT_AI_RERANK_MAX_DOCUMENTS", 30, MIN_DOCUMENTS, MAX_DOCUMENTS
        ),
        api_key_configured=bool(api_key),
        api_key_hint=f"••••{api_key[-4:]}" if api_key else None,
        updated_at=None,
    )


def resolved_reranker(
    session: Session,
    *,
    timeout_cap_ms: int | None = None,
    max_documents_cap: int | None = None,
) -> CohereCompatibleReranker | None:
    def bounded_timeout(value: int) -> int:
        return min(value, timeout_cap_ms) if timeout_cap_ms is not None else value

    def bounded_documents(value: int) -> int:
        return (
            min(value, max_documents_cap)
            if max_documents_cap is not None
            else value
        )

    settings = get_managed_rerank_settings(session)
    if settings is not None:
        if not settings.is_active:
            return None
        return _cached_reranker(
            decrypt_api_key(settings.api_key_ciphertext),
            settings.base_url,
            settings.model_name,
            bounded_timeout(settings.timeout_ms),
            bounded_documents(settings.max_documents),
        )
    snapshot = rerank_configuration_snapshot(session)
    if not snapshot.enabled or not snapshot.base_url or not snapshot.model_name:
        return None
    api_key = os.getenv("SUPPORT_AI_RERANK_API_KEY", "").strip()
    return _cached_reranker(
        api_key,
        snapshot.base_url,
        snapshot.model_name,
        bounded_timeout(snapshot.timeout_ms),
        bounded_documents(snapshot.max_documents),
    )


def save_managed_rerank_settings(
    session: Session,
    *,
    enabled: bool,
    base_url: str,
    model_name: str,
    timeout_ms: int,
    max_documents: int,
    api_key: str | None,
    updated_by_user_id: UUID,
) -> RerankProviderSettingsRow:
    normalized_base_url = base_url.strip().rstrip("/")
    normalized_model = model_name.strip()
    rerank_endpoint(normalized_base_url)
    if not normalized_model:
        raise RerankProviderError("rerank model is required")
    if timeout_ms < MIN_TIMEOUT_MS or timeout_ms > MAX_TIMEOUT_MS:
        raise RerankProviderError("rerank timeout must be between 100 and 800 ms")
    if max_documents < MIN_DOCUMENTS or max_documents > MAX_DOCUMENTS:
        raise RerankProviderError("rerank max documents must be between 5 and 30")

    settings = get_managed_rerank_settings(session)
    normalized_key = api_key.strip() if api_key is not None else ""
    if settings is None and not normalized_key:
        normalized_key = os.getenv("SUPPORT_AI_RERANK_API_KEY", "").strip()
    if settings is None and not normalized_key:
        raise RerankProviderError(
            "rerank API key is required for the first configuration"
        )
    if settings is None:
        settings = RerankProviderSettingsRow(
            id=SETTINGS_ID,
            provider="cohere-compatible",
            base_url=normalized_base_url,
            model_name=normalized_model,
            timeout_ms=timeout_ms,
            max_documents=max_documents,
            api_key_ciphertext=encrypt_api_key(normalized_key),
            api_key_last_four=normalized_key[-4:] or None,
            is_active=enabled,
            version=1,
            updated_by_user_id=updated_by_user_id,
        )
        session.add(settings)
    else:
        settings.base_url = normalized_base_url
        settings.model_name = normalized_model
        settings.timeout_ms = timeout_ms
        settings.max_documents = max_documents
        settings.is_active = enabled
        settings.version += 1
        settings.updated_by_user_id = updated_by_user_id
        settings.updated_at = utcnow()
        if normalized_key:
            settings.api_key_ciphertext = encrypt_api_key(normalized_key)
            settings.api_key_last_four = normalized_key[-4:]
    session.flush()
    _cached_reranker.cache_clear()
    return settings
