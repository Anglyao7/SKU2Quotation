from __future__ import annotations

from uuid import uuid4

from app.use_cases import workspace


def test_dashboard_health_clamps_inconsistent_legacy_counts(monkeypatch) -> None:
    monkeypatch.setattr(
        workspace.repository,
        "dashboard_snapshot",
        lambda *_args, **_kwargs: {
            "active_skus": 1,
            "today_inquiries": 0,
            "open_inquiries": 0,
            "pending_quotes": 0,
            "pending_reviews": 0,
            "active_suppliers": 0,
            "recent_imports": [],
            "active_products": 1,
            "approved_images": 601,
            "sourced_products": 3,
            "priced_products": 2,
        },
    )

    response = workspace.get_dashboard(
        object(),
        tenant_id=uuid4(),
        membership_id=uuid4(),
        permissions=frozenset({"product.view"}),
        import_limit=6,
    )

    assert response.data_health is not None
    assert response.data_health.score == 100
    assert response.data_health.approved_image_coverage == 1
    assert response.data_health.supplier_source_coverage == 1
    assert response.data_health.valid_price_coverage == 1
