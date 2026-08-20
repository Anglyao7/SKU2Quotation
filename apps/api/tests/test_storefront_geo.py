from __future__ import annotations

from fastapi import Request

from app.services import storefront_analytics as service


def _request(*, ip: str) -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "https",
            "path": "/api/store/demo/skus/example/views",
            "raw_path": b"/api/store/demo/skus/example/views",
            "query_string": b"",
            "headers": [],
            "client": (ip, 43120),
            "server": ("example.com", 443),
        }
    )


def test_public_ip_country_fallback_is_cached(monkeypatch) -> None:
    calls: list[str] = []

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"success": True, "country_code": "US"}

    def fake_get(url: str, **_kwargs: object) -> Response:
        calls.append(url)
        return Response()

    monkeypatch.setenv("TRUST_CLOUDFLARE_VISITOR_HEADERS", "false")
    monkeypatch.setattr(service.httpx, "get", fake_get)
    service._geo_cache.clear()

    request = _request(ip="8.8.4.4")
    assert service.request_country_code(request, visitor_ip="8.8.4.4") == "US"
    assert service.request_country_code(request, visitor_ip="8.8.4.4") == "US"
    assert calls == ["https://ipwho.is/8.8.4.4"]


def test_private_ip_does_not_call_external_geo_service(monkeypatch) -> None:
    def fail_get(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("private addresses must not be sent to a geo provider")

    monkeypatch.setattr(service.httpx, "get", fail_get)
    assert service.lookup_country_code("192.168.1.20") == "ZZ"
