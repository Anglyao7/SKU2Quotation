from datetime import datetime

from pydantic import BaseModel, Field


class OutboxMetricsResponse(BaseModel):
    pending_count: int
    processing_count: int
    failed_count: int
    dead_count: int
    oldest_unpublished_at: datetime | None
    lag_seconds: float


class CpuUsageResponse(BaseModel):
    utilization_percent: float | None = Field(default=None, ge=0, le=100)
    logical_cores: int = Field(ge=1)
    quota_cores: float | None = Field(default=None, gt=0)
    load_1m: float | None = Field(default=None, ge=0)
    load_5m: float | None = Field(default=None, ge=0)
    load_15m: float | None = Field(default=None, ge=0)


class MemoryUsageResponse(BaseModel):
    used_bytes: int | None = Field(default=None, ge=0)
    total_bytes: int | None = Field(default=None, ge=0)
    available_bytes: int | None = Field(default=None, ge=0)
    utilization_percent: float | None = Field(default=None, ge=0, le=100)
    container_used_bytes: int | None = Field(default=None, ge=0)
    container_limit_bytes: int | None = Field(default=None, ge=0)


class DiskUsageResponse(BaseModel):
    mount_path: str
    used_bytes: int = Field(ge=0)
    total_bytes: int = Field(ge=0)
    available_bytes: int = Field(ge=0)
    utilization_percent: float = Field(ge=0, le=100)


class SystemMonitoringResponse(BaseModel):
    sampled_at: datetime
    scope: str
    uptime_seconds: float | None = Field(default=None, ge=0)
    cpu: CpuUsageResponse
    memory: MemoryUsageResponse
    disk: DiskUsageResponse
