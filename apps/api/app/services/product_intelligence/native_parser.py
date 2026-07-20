from .contracts import (
    ProductCandidateDraft,
    ProductFieldDraft,
    ProductParseRequest,
    ProductParseResult,
)


class NativeSupplierFileParserAdapter:
    """Deterministic XLSX/CSV candidate adapter with no external AI dependency."""

    adapter_key = "native-supplier-file-parser"
    adapter_version = "1.0"
    provider_type = "NATIVE"

    def parse(self, request: ProductParseRequest) -> ProductParseResult:
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
                "parser_mode": "native",
                "source_file_id": request.source_file_id,
                "network_calls": 0,
                "ocr_calls": 0,
                "vision_calls": 0,
                "llm_calls": 0,
                "embedding_calls": 0,
            },
        )
