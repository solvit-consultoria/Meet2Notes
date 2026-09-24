from __future__ import annotations

from types import SimpleNamespace

from local_meeting_ai.infrastructure import system_performance


class _CpuTimes:
    def __init__(self, values: dict[str, float]) -> None:
        self.values = values

    def _asdict(self) -> dict[str, float]:
        return self.values


def test_cpu_usage_uses_two_nonblocking_samples(monkeypatch) -> None:
    samples = iter(
        [
            _CpuTimes({"user": 40, "system": 40, "idle": 20}),
            _CpuTimes({"user": 80, "system": 95, "idle": 25}),
        ]
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "psutil",
        SimpleNamespace(cpu_times=lambda: next(samples)),
    )
    sampler = system_performance.SystemPerformanceSampler()

    assert sampler._sample_cpu_usage() is None
    assert sampler._sample_cpu_usage() == 95.0


def test_gpu_probe_runs_in_throttled_daemon_thread(monkeypatch) -> None:
    now = [100.0]
    threads = []

    class _Thread:
        def __init__(self, *, target, **kwargs):
            self.target = target
            self.kwargs = kwargs
            threads.append(self)

        def start(self):
            pass

    monkeypatch.setattr(system_performance.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(system_performance.threading, "Thread", _Thread)
    sampler = system_performance.SystemPerformanceSampler()

    first = sampler.snapshot()
    second = sampler.snapshot()

    assert first["gpu_metrics_available"] is False
    assert second["gpu_usage_percent"] is None
    assert len(threads) == 1
    assert threads[0].kwargs["daemon"] is True
    assert threads[0].kwargs["name"] == "system-performance-gpu-probe"


def test_gpu_probe_parses_utilization_and_vram(monkeypatch) -> None:
    monkeypatch.setattr(system_performance.shutil, "which", lambda _name: "nvidia-smi")
    monkeypatch.setattr(
        system_performance.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout="43, 1024, 4096\n"),
    )
    sampler = system_performance.SystemPerformanceSampler()

    sampler._refresh_gpu_snapshot()

    snapshot = sampler.snapshot()
    assert snapshot["gpu_available"] is True
    assert snapshot["gpu_metrics_available"] is True
    assert snapshot["gpu_usage_percent"] == 43.0
    assert snapshot["gpu_memory_used_bytes"] == 1024 * 1024 * 1024
    assert snapshot["gpu_memory_total_bytes"] == 4096 * 1024 * 1024
