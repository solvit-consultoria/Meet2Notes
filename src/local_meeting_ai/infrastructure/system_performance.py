"""Low-overhead system utilization snapshots for the optional performance panel."""

from __future__ import annotations

import csv
import io
import os
import shutil
import subprocess
import threading
import time
from typing import Any

GPU_REFRESH_SECONDS = 5.0
GPU_PROBE_TIMEOUT_SECONDS = 1.5


class SystemPerformanceSampler:
    """Sample CPU locally and refresh NVIDIA metrics outside request threads."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._previous_cpu: tuple[float, float] | None = None
        self._gpu_snapshot: dict[str, Any] = {
            "gpu_available": False,
            "gpu_metrics_available": False,
            "gpu_usage_percent": None,
            "gpu_memory_used_bytes": None,
            "gpu_memory_total_bytes": None,
        }
        self._gpu_refresh_started_at = 0.0
        self._gpu_refresh_in_progress = False

    def snapshot(self) -> dict[str, Any]:
        cpu_usage = self._sample_cpu_usage()
        self._schedule_gpu_refresh()
        with self._lock:
            gpu = dict(self._gpu_snapshot)
        return {
            "cpu_usage_percent": cpu_usage,
            "cpu_usage_available": cpu_usage is not None,
            **gpu,
        }

    def _sample_cpu_usage(self) -> float | None:
        try:
            import psutil  # type: ignore[import-untyped]

            values = psutil.cpu_times()
            fields = values._asdict()
            idle = float(fields.get("idle", 0.0)) + float(fields.get("iowait", 0.0))
            total = sum(float(value) for value in fields.values())
        except Exception:
            return None

        with self._lock:
            previous = self._previous_cpu
            self._previous_cpu = (total, idle)
        if previous is None:
            return None
        total_delta = total - previous[0]
        idle_delta = idle - previous[1]
        if total_delta <= 0:
            return None
        return round(min(100.0, max(0.0, (1 - idle_delta / total_delta) * 100)), 1)

    def _schedule_gpu_refresh(self) -> None:
        now = time.monotonic()
        with self._lock:
            refresh_is_recent = now - self._gpu_refresh_started_at < GPU_REFRESH_SECONDS
            if self._gpu_refresh_in_progress or refresh_is_recent:
                return
            self._gpu_refresh_started_at = now
            self._gpu_refresh_in_progress = True
        worker = threading.Thread(
            target=self._refresh_gpu_snapshot,
            name="system-performance-gpu-probe",
            daemon=True,
        )
        try:
            worker.start()
        except RuntimeError:
            with self._lock:
                self._gpu_refresh_in_progress = False

    def _refresh_gpu_snapshot(self) -> None:
        snapshot: dict[str, Any] = {
            "gpu_available": False,
            "gpu_metrics_available": False,
            "gpu_usage_percent": None,
            "gpu_memory_used_bytes": None,
            "gpu_memory_total_bytes": None,
        }
        command = shutil.which("nvidia-smi")
        if command:
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
            try:
                completed = subprocess.run(
                    [
                        command,
                        "--query-gpu=utilization.gpu,memory.used,memory.total",
                        "--format=csv,noheader,nounits",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=GPU_PROBE_TIMEOUT_SECONDS,
                    check=True,
                    creationflags=flags,
                )
                rows = list(csv.reader(io.StringIO(completed.stdout)))
                if rows and len(rows[0]) >= 3:
                    metrics = (float(value.strip()) for value in rows[0][:3])
                    utilization, used_mib, total_mib = metrics
                    snapshot = {
                        "gpu_available": True,
                        "gpu_metrics_available": True,
                        "gpu_usage_percent": round(min(100.0, max(0.0, utilization)), 1),
                        "gpu_memory_used_bytes": int(used_mib * 1024 * 1024),
                        "gpu_memory_total_bytes": int(total_mib * 1024 * 1024),
                    }
            except (OSError, subprocess.SubprocessError, ValueError):
                pass
        with self._lock:
            self._gpu_snapshot = snapshot
            self._gpu_refresh_in_progress = False


_system_performance_sampler = SystemPerformanceSampler()


def system_performance_snapshot() -> dict[str, Any]:
    return _system_performance_sampler.snapshot()
