from datetime import datetime

from pydantic import BaseModel


class OutboxMetricsResponse(BaseModel):
    pending_count: int
    processing_count: int
    failed_count: int
    dead_count: int
    oldest_unpublished_at: datetime | None
    lag_seconds: float

