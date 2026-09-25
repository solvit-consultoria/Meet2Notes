from __future__ import annotations

import hashlib
import wave
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from local_meeting_ai.application.source_track_attribution import (
    preview_source_track_attribution,
    resolve_capture_master_pair,
)


def _write_track(path: Path, active_windows: set[int]) -> tuple[str, int]:
    samples_per_window = 320  # 20 ms at 16 kHz
    values = np.zeros(100 * samples_per_window, dtype="<i2")
    for window in active_windows:
        start = window * samples_per_window
        values[start : start + samples_per_window] = 5000
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16_000)
        output.writeframes(values.tobytes())
    return hashlib.sha256(path.read_bytes()).hexdigest(), 2_000


def _segment(index: int, start: int, end: int) -> SimpleNamespace:
    return SimpleNamespace(segment_index=index, start_ms=start, end_ms=end)


def test_legacy_capture_without_source_manifest_resolves_exact_synced_masters() -> None:
    original = SimpleNamespace(id=8, meeting_id=3, role="original", metadata={})
    microphone = SimpleNamespace(
        id=9,
        meeting_id=3,
        role="master_microphone",
        metadata={
            "synchronized_with_recording_id": 8,
            "capture_source_kind": "microphone",
        },
    )
    system = SimpleNamespace(
        id=10,
        meeting_id=3,
        role="master_system",
        metadata={
            "synchronized_with_recording_id": 8,
            "capture_source_kind": "system",
        },
    )

    assert resolve_capture_master_pair(
        source_recording=original,
        recordings=[microphone, system],
        meeting_id=3,
    ) == (microphone, system)


def test_source_pair_rejects_wrong_sync_or_inconsistent_present_manifest() -> None:
    original = SimpleNamespace(
        id=8,
        meeting_id=3,
        role="original",
        metadata={"capture_sources": [{"kind": "microphone"}]},
    )
    microphone = SimpleNamespace(
        id=9,
        meeting_id=3,
        role="master_microphone",
        metadata={
            "synchronized_with_recording_id": 8,
            "capture_source_kind": "microphone",
        },
    )
    system = SimpleNamespace(
        id=10,
        meeting_id=3,
        role="master_system",
        metadata={
            "synchronized_with_recording_id": 7,
            "capture_source_kind": "system",
        },
    )

    assert resolve_capture_master_pair(
        source_recording=original,
        recordings=[microphone, system],
        meeting_id=3,
    ) is None


def _preview(
    tmp_path: Path,
    *,
    mic_windows: set[int] | None = None,
    system_windows: set[int] | None = None,
    **overrides,
):
    mic_path = tmp_path / "microphone.wav"
    system_path = tmp_path / "system.wav"
    mic_hash, duration = _write_track(
        mic_path,
        mic_windows if mic_windows is not None else set(range(20)) | set(range(40, 50)),
    )
    system_hash, _ = _write_track(
        system_path,
        system_windows
        if system_windows is not None
        else set(range(20, 40)) | set(range(40, 50)),
    )
    arguments = {
        "segments": [_segment(0, 0, 400), _segment(1, 400, 800), _segment(2, 800, 1000)],
        "microphone_path": mic_path,
        "system_path": system_path,
        "microphone_sha256": mic_hash,
        "system_sha256": system_hash,
        "microphone_duration_ms": duration,
        "system_duration_ms": duration,
        "microphone_sync_id": 42,
        "system_sync_id": 42,
        "confirm_one_to_one": True,
        "speaker_count": 2,
        "confirm_mapping": True,
        "microphone_speaker": "Thomas",
        "system_speaker": "Rafa",
    }
    arguments.update(overrides)
    return preview_source_track_attribution(**arguments)


def test_source_track_preview_maps_clear_turns_and_leaves_overlap_unknown(
    tmp_path: Path,
) -> None:
    result = _preview(tmp_path)

    assert result["persisted"] is False
    assert [row["speaker"] for row in result["segments"]] == [
        "Thomas",
        "Rafa",
        None,
    ]
    assert result["segments"][0]["source_role"] == "master_microphone"
    assert result["segments"][1]["source_role"] == "master_system"
    assert "Both sources" in result["segments"][2]["reason"]


def test_low_effective_confidence_stays_unknown(tmp_path: Path) -> None:
    result = _preview(
        tmp_path,
        segments=[_segment(0, 0, 440)],
        mic_windows=set(range(20)),
        system_windows=set(range(18, 22)),
    )

    assert result["segments"][0]["speaker"] is None
    assert "confidence threshold" in result["segments"][0]["reason"]


@pytest.mark.parametrize(
    ("overrides", "expected_reason"),
    [
        ({"microphone_sha256": "not-the-hash"}, "hash changed"),
        ({"microphone_duration_ms": 3000}, "durations do not match"),
        ({"system_sync_id": 43}, "do not share a verified capture source"),
    ],
)
def test_source_pair_mismatch_returns_unknown_without_labels(
    tmp_path: Path, overrides: dict[str, object], expected_reason: str
) -> None:
    result = _preview(tmp_path, **overrides)

    assert all(row["speaker"] is None for row in result["segments"])
    assert expected_reason in result["warning"]


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"confirm_one_to_one": False}, "one-to-one"),
        ({"speaker_count": 3}, "exactly 2 speakers"),
        ({"confirm_mapping": False}, "mapping"),
        ({"system_speaker": " thomas "}, "two distinct speaker names"),
    ],
)
def test_preview_requires_explicit_confirmations_and_distinct_names(
    tmp_path: Path, overrides: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        _preview(tmp_path, **overrides)
