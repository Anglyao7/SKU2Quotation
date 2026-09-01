from types import SimpleNamespace
from uuid import uuid4

from scripts.repair_repeated_sku_names import (
    _candidate_repairs,
    _collapse_translated_repetition,
)


def test_repair_candidates_only_collapse_exact_specification_suffixes() -> None:
    repeated = SimpleNamespace(
        id=uuid4(),
        name="冰垫 · 高级灰 / L · 高级灰 / L · 高级灰 / L",
        option_values={"规格名称": "高级灰 / L"},
    )
    unrelated = SimpleNamespace(
        id=uuid4(),
        name="买二送二 · 促销装 · 促销装",
        option_values={"规格名称": "家庭装"},
    )

    repairs = _candidate_repairs([repeated, unrelated])

    assert len(repairs) == 1
    assert repairs[0].sku_id == repeated.id
    assert repairs[0].repetition_count == 3
    assert repairs[0].after == "冰垫 · 高级灰 / L"


def test_translated_name_cleanup_requires_identical_adjacent_suffixes() -> None:
    assert _collapse_translated_repetition(
        "Tapis · Gris / L · Gris / L · Gris / L",
        maximum_removals=2,
    ) == "Tapis · Gris / L"
    assert _collapse_translated_repetition(
        "Tapis · Gris / L · Grand",
        maximum_removals=2,
    ) == "Tapis · Gris / L · Grand"
