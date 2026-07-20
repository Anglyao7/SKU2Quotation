from dataclasses import dataclass, field
from typing import Any, Protocol, Sequence, runtime_checkable


CANDIDATE_REVIEW_STATUS = "AI_SUGGESTED"


@dataclass(frozen=True, slots=True)
class NativeField:
    key: str
    raw_value: str
    normalized_value: Any
    confidence: float | None
    source_location: str


@dataclass(frozen=True, slots=True)
class NativeProductRecord:
    candidate_group_key: str
    candidate_index: int
    source_location: str
    fields: tuple[NativeField, ...]


@dataclass(frozen=True, slots=True)
class ProductParseRequest:
    source_file_id: str
    source_hash: str
    records: tuple[NativeProductRecord, ...]


@dataclass(frozen=True, slots=True)
class ProductFieldDraft:
    field_key: str
    raw_value: str
    normalized_value: Any
    confidence: float | None
    source_location: str
    validation_status: str = "PASS"
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ProductCandidateDraft:
    candidate_group_key: str
    candidate_index: int
    fields: tuple[ProductFieldDraft, ...]
    review_status: str = CANDIDATE_REVIEW_STATUS


@dataclass(frozen=True, slots=True)
class ProductParseResult:
    candidates: tuple[ProductCandidateDraft, ...]
    warnings: tuple[str, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)


class ProductParserError(RuntimeError):
    """Safe, classified provider failure that can be persisted without secret leakage."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.safe_message = message


@runtime_checkable
class ProductParserPort(Protocol):
    """Provider-neutral product parser port; implementations return drafts only."""

    adapter_key: str
    adapter_version: str
    provider_type: str

    def parse(self, request: ProductParseRequest) -> ProductParseResult:
        """Return Candidate Drafts without mutating Product or ProductAttribute rows."""
        ...


def require_candidate_only(result: ProductParseResult) -> None:
    if any(candidate.review_status != CANDIDATE_REVIEW_STATUS for candidate in result.candidates):
        raise ValueError("Provider output must remain AI_SUGGESTED Candidate Draft data")


def freeze_records(records: Sequence[NativeProductRecord]) -> tuple[NativeProductRecord, ...]:
    return tuple(records)
