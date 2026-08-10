from __future__ import annotations

from .catalog_translations import recover_interrupted_translation_jobs
from .knowledge_search import recover_interrupted_index_jobs


def recover_interrupted_jobs() -> int:
    """Recover API-process background jobs into durable resumable states."""

    return (
        recover_interrupted_translation_jobs()
        + recover_interrupted_index_jobs()
    )
