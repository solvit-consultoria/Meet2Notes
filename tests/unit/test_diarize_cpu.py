from __future__ import annotations

import io
import threading
import time

import pytest

from local_meeting_ai.adapters.diarization.diarize_cpu import DiarizeCpuEngine
from local_meeting_ai.domain.errors import CapabilityUnavailableError, JobCancelledError


class _BlockingStdout:
    def __init__(self, stopped: threading.Event) -> None:
        self.stopped = stopped

    def readline(self) -> str:
        self.stopped.wait(timeout=10)
        return ""


class _FakeProcess:
    def __init__(self) -> None:
        self.stopped = threading.Event()
        self.stdin = io.StringIO()
        self.stdout = _BlockingStdout(self.stopped)
        self.returncode: int | None = None
        self.terminated = False

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 1
        self.stopped.set()

    def wait(self, timeout: float | None = None) -> int:
        if not self.stopped.wait(timeout):
            raise TimeoutError
        return self.returncode or 0

    def kill(self) -> None:
        self.terminate()


def test_request_worker_cancels_blocked_output_and_stops_subprocess(
    tmp_path,
) -> None:
    engine = DiarizeCpuEngine(tmp_path / "models")
    process = _FakeProcess()
    engine._process = process  # type: ignore[assignment]
    cancelled = threading.Event()

    def cancel_soon() -> None:
        time.sleep(0.05)
        cancelled.set()

    canceller = threading.Thread(target=cancel_soon, daemon=True)
    canceller.start()
    started = time.monotonic()
    try:
        with pytest.raises(JobCancelledError, match="Diarization was cancelled"):
            engine._request_worker({"action": "diarize"}, cancelled.is_set)
    finally:
        engine.unload()
        engine.shutdown()
        canceller.join(timeout=1)

    assert time.monotonic() - started < 2
    assert process.terminated
    assert engine._process is None


def test_request_worker_timeout_stops_blocked_subprocess(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = DiarizeCpuEngine(tmp_path / "models")
    process = _FakeProcess()
    engine._process = process  # type: ignore[assignment]
    monkeypatch.setattr(
        "local_meeting_ai.adapters.diarization.diarize_cpu._WORKER_TIMEOUT_SECONDS",
        0,
    )

    try:
        with pytest.raises(CapabilityUnavailableError, match="diarize CPU worker timed out"):
            engine._request_worker({"action": "diarize"})
    finally:
        engine.unload()
        engine.shutdown()

    assert process.terminated
    assert engine._process is None
