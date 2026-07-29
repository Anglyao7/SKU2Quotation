from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from threading import Lock

from ..model_mixins import utcnow
from ..system_schemas import (
    CpuUsageResponse,
    DiskUsageResponse,
    MemoryUsageResponse,
    SystemMonitoringResponse,
)


_CPU_SAMPLE_LOCK = Lock()
_previous_cpu_sample: tuple[int, int] | None = None


def _read_text(path: str, *, limit: int = 16_384) -> str | None:
    try:
        with Path(path).open("r", encoding="utf-8") as handle:
            return handle.read(limit).strip()
    except (OSError, UnicodeError):
        return None


def _run_text(command: list[str], *, limit: int = 16_384) -> str | None:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            check=False,
            text=True,
            timeout=1,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout[:limit].strip() or None


def _percentage(used: int, total: int) -> float | None:
    if total <= 0:
        return None
    return round(max(0.0, min(100.0, used / total * 100.0)), 2)


def _proc_cpu_sample() -> tuple[int, int] | None:
    content = _read_text("/proc/stat")
    if not content:
        return None
    first_line = content.splitlines()[0].split()
    if not first_line or first_line[0] != "cpu":
        return None
    try:
        values = [int(value) for value in first_line[1:]]
    except ValueError:
        return None
    if len(values) < 4:
        return None
    total = sum(values)
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    return total, idle


def _load_average() -> tuple[float | None, float | None, float | None]:
    try:
        one, five, fifteen = os.getloadavg()
        return (
            max(0.0, round(one, 3)),
            max(0.0, round(five, 3)),
            max(0.0, round(fifteen, 3)),
        )
    except (AttributeError, OSError):
        return None, None, None


def _cpu_quota_cores() -> float | None:
    cpu_max = _read_text("/sys/fs/cgroup/cpu.max", limit=128)
    if cpu_max:
        parts = cpu_max.split()
        if len(parts) >= 2 and parts[0] != "max":
            try:
                quota = int(parts[0])
                period = int(parts[1])
                if quota > 0 and period > 0:
                    return round(quota / period, 3)
            except ValueError:
                pass
    quota_text = _read_text(
        "/sys/fs/cgroup/cpu/cpu.cfs_quota_us", limit=64
    )
    period_text = _read_text(
        "/sys/fs/cgroup/cpu/cpu.cfs_period_us", limit=64
    )
    if quota_text and period_text:
        try:
            quota = int(quota_text)
            period = int(period_text)
            if quota > 0 and period > 0:
                return round(quota / period, 3)
        except ValueError:
            pass
    return None


def _cpu_usage() -> CpuUsageResponse:
    global _previous_cpu_sample

    logical_cores = max(1, int(os.cpu_count() or 1))
    load_1m, load_5m, load_15m = _load_average()
    current = _proc_cpu_sample()
    utilization: float | None = None
    if current is not None:
        with _CPU_SAMPLE_LOCK:
            previous = _previous_cpu_sample
            _previous_cpu_sample = current
        if previous is not None:
            total_delta = current[0] - previous[0]
            idle_delta = current[1] - previous[1]
            if total_delta > 0:
                utilization = round(
                    max(
                        0.0,
                        min(100.0, (total_delta - max(0, idle_delta)) / total_delta * 100.0),
                    ),
                    2,
                )
    if utilization is None and load_1m is not None:
        utilization = round(
            max(0.0, min(100.0, load_1m / logical_cores * 100.0)),
            2,
        )
    return CpuUsageResponse(
        utilization_percent=utilization,
        logical_cores=logical_cores,
        quota_cores=_cpu_quota_cores(),
        load_1m=load_1m,
        load_5m=load_5m,
        load_15m=load_15m,
    )


def _proc_memory() -> tuple[int, int, int] | None:
    content = _read_text("/proc/meminfo")
    if not content:
        return None
    values: dict[str, int] = {}
    for line in content.splitlines():
        key, separator, raw_value = line.partition(":")
        if not separator:
            continue
        try:
            values[key] = int(raw_value.strip().split()[0]) * 1024
        except (IndexError, ValueError):
            continue
    total = values.get("MemTotal")
    if not total:
        return None
    available = values.get("MemAvailable")
    if available is None:
        available = sum(
            values.get(key, 0)
            for key in ("MemFree", "Buffers", "Cached", "SReclaimable")
        )
    available = max(0, min(total, available))
    return total - available, total, available


def _darwin_memory() -> tuple[int, int, int] | None:
    if sys.platform != "darwin":
        return None
    try:
        page_count = int(os.sysconf("SC_PHYS_PAGES"))
        page_size = int(os.sysconf("SC_PAGE_SIZE"))
    except (AttributeError, OSError, TypeError, ValueError):
        return None
    total = page_count * page_size
    content = _run_text(["/usr/bin/vm_stat"])
    if total <= 0 or not content:
        return None
    match = re.search(r"page size of (\d+) bytes", content)
    if match:
        page_size = int(match.group(1))
    pages: dict[str, int] = {}
    for line in content.splitlines()[1:]:
        key, separator, raw_value = line.partition(":")
        if not separator:
            continue
        try:
            pages[key.strip()] = int(raw_value.strip().rstrip("."))
        except ValueError:
            continue
    available_pages = sum(
        pages.get(key, 0)
        for key in ("Pages free", "Pages inactive", "Pages speculative")
    )
    available = max(0, min(total, available_pages * page_size))
    return total - available, total, available


def _cgroup_memory() -> tuple[int | None, int | None]:
    current_text = _read_text("/sys/fs/cgroup/memory.current", limit=64)
    maximum_text = _read_text("/sys/fs/cgroup/memory.max", limit=64)
    if current_text:
        try:
            current = max(0, int(current_text))
        except ValueError:
            current = None
        try:
            maximum = (
                max(0, int(maximum_text))
                if maximum_text and maximum_text != "max"
                else None
            )
        except ValueError:
            maximum = None
        return current, maximum
    current_text = _read_text(
        "/sys/fs/cgroup/memory/memory.usage_in_bytes", limit=64
    )
    maximum_text = _read_text(
        "/sys/fs/cgroup/memory/memory.limit_in_bytes", limit=64
    )
    try:
        current = max(0, int(current_text)) if current_text else None
    except ValueError:
        current = None
    try:
        maximum = max(0, int(maximum_text)) if maximum_text else None
    except ValueError:
        maximum = None
    # cgroup v1 often represents "unlimited" with an extremely large sentinel.
    if maximum is not None and maximum >= 1 << 60:
        maximum = None
    return current, maximum


def _memory_usage() -> MemoryUsageResponse:
    host = _proc_memory() or _darwin_memory()
    container_used, container_limit = _cgroup_memory()
    if host is None:
        return MemoryUsageResponse(
            container_used_bytes=container_used,
            container_limit_bytes=container_limit,
        )
    used, total, available = host
    return MemoryUsageResponse(
        used_bytes=used,
        total_bytes=total,
        available_bytes=available,
        utilization_percent=_percentage(used, total),
        container_used_bytes=container_used,
        container_limit_bytes=container_limit,
    )


def _disk_usage() -> DiskUsageResponse:
    configured_path = os.getenv("SYSTEM_MONITOR_DISK_PATH", "/").strip() or "/"
    mount_path = configured_path if Path(configured_path).exists() else "/"
    usage = shutil.disk_usage(mount_path)
    return DiskUsageResponse(
        mount_path=mount_path,
        used_bytes=usage.used,
        total_bytes=usage.total,
        available_bytes=usage.free,
        utilization_percent=_percentage(usage.used, usage.total) or 0.0,
    )


def _uptime_seconds() -> float | None:
    content = _read_text("/proc/uptime", limit=128)
    if not content:
        return None
    try:
        return max(0.0, round(float(content.split()[0]), 1))
    except (IndexError, ValueError):
        pass
    return None


def _darwin_uptime_seconds() -> float | None:
    if sys.platform != "darwin":
        return None
    content = _run_text(["/usr/sbin/sysctl", "-n", "kern.boottime"], limit=512)
    if not content:
        return None
    match = re.search(r"sec\s*=\s*(\d+)", content)
    if not match:
        return None
    return max(0.0, round(time.time() - int(match.group(1)), 1))


def system_monitoring_snapshot() -> SystemMonitoringResponse:
    return SystemMonitoringResponse(
        sampled_at=utcnow(),
        scope="SERVER_HOST",
        uptime_seconds=_uptime_seconds() or _darwin_uptime_seconds(),
        cpu=_cpu_usage(),
        memory=_memory_usage(),
        disk=_disk_usage(),
    )
