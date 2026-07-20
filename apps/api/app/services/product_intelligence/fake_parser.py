from .contracts import (
    ProductCandidateDraft,
    ProductFieldDraft,
    ProductParseRequest,
    ProductParseResult,
    ProductParserError,
)


class FakeProductParserAdapter:
    """Deterministic and network-free adapter for contract and recovery testing."""

    adapter_key = "fake-native-product-parser"
    adapter_version = "1.0"
    provider_type = "FAKE"

    def __init__(self, *, fail_first_attempt: bool = False) -> None:
        self._failures_remaining = 1 if fail_first_attempt else 0

    def parse(self, request: ProductParseRequest) -> ProductParseResult:
        if self._failures_remaining:
            self._failures_remaining -= 1
            raise ProductParserError(
                "FAKE_TRANSIENT_FAILURE",
                "The deterministic fake parser failed before producing any candidate draft.",
            )

        candidates = tuple(
            ProductCandidateDraft(
                candidate_group_key=record.candidate_group_key,
                candidate_index=record.candidate_index,
                fields=tuple(
                    ProductFieldDraft(
                        field_key=field.key,
                        raw_value=field.raw_value,
                        normalized_value=field.normalized_value,
                        confidence=field.confidence,
                        source_location=field.source_location,
                    )
                    for field in record.fields
                ),
            )
            for record in request.records
        )
        return ProductParseResult(
            candidates=candidates,
            diagnostics={
                "network_calls": 0,
                "ocr_calls": 0,
                "vision_calls": 0,
                "llm_calls": 0,
                "embedding_calls": 0,
            },
        )
