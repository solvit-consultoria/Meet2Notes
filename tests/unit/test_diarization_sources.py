from __future__ import annotations

from pathlib import Path

import pytest

from local_meeting_ai.api.schemas import DiarizationStartRequest
from local_meeting_ai.application.ai_services import select_synchronized_masters
from local_meeting_ai.domain.entities import Recording
from local_meeting_ai.domain.errors import ValidationError


def _recording(
    *, role: str, path: Path, metadata: dict[str, object], duration_ms: int = 1000
) -> Recording:
    return Recording(
        id=1, meeting_id=3, role=role, local_path=str(path),
        original_filename=None, media_type="audio/wav", size_bytes=1,
        duration_ms=duration_ms, sample_rate=48000, channels=1, sha256=None,
        metadata=metadata, created_at="now",
    )


def test_selects_matching_microphone_and_system_masters(tmp_path: Path) -> None:
    mic_path = tmp_path / "mic.wav"
    system_path = tmp_path / "system.wav"
    mic_path.touch()
    system_path.touch()
    normalized = _recording(
        role="normalized", path=tmp_path / "normalized.wav",
        metadata={"source_recording_id": 44},
    )
    microphone = _recording(
        role="master_microphone", path=mic_path,
        metadata={"synchronized_with_recording_id": 44},
    )
    system = _recording(
        role="master_system", path=system_path,
        metadata={"synchronized_with_recording_id": 44},
    )
    newer_unmatched_microphone = _recording(
        role="master_microphone", path=mic_path,
        metadata={"synchronized_with_recording_id": 45},
    )

    assert select_synchronized_masters(
        normalized, [newer_unmatched_microphone, system, microphone]
    ) == (
        microphone, system
    )


def test_rejects_master_from_different_source_or_duration(tmp_path: Path) -> None:
    mic_path = tmp_path / "mic.wav"
    system_path = tmp_path / "system.wav"
    mic_path.touch()
    system_path.touch()
    normalized = _recording(
        role="normalized", path=tmp_path / "normalized.wav",
        metadata={"source_recording_id": 44},
    )
    microphone = _recording(
        role="master_microphone", path=mic_path,
        metadata={"synchronized_with_recording_id": 44},
    )
    unsynced_system = _recording(
        role="master_system", path=system_path,
        metadata={"synchronized_with_recording_id": 45},
    )
    with pytest.raises(ValidationError, match="unavailable"):
        select_synchronized_masters(normalized, [microphone, unsynced_system])

    short_system = _recording(
        role="master_system", path=system_path,
        metadata={"synchronized_with_recording_id": 44}, duration_ms=999,
    )
    with pytest.raises(ValidationError, match="not aligned"):
        select_synchronized_masters(normalized, [microphone, short_system])


def test_mono_mode_remains_the_default() -> None:
    assert DiarizationStartRequest.model_validate({}).use_synchronized_masters is False
