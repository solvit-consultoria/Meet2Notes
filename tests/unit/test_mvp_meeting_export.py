from __future__ import annotations

import hashlib
import json
import wave
from dataclasses import replace
from pathlib import Path

import pytest

from local_meeting_ai.domain.entities import (
    Meeting,
    Recording,
    Transcription,
    TranscriptSegment,
)
from local_meeting_ai.domain.enums import MeetingStatus, SourceType
from local_meeting_ai.infrastructure.meeting_export import export_meeting_bundle


def _meeting() -> Meeting:
    return Meeting(
        id=9,
        uuid="55c8b172-6dd3-4c20-8316-d61a5b8b2c66",
        title="Call do cliente",
        description=None,
        status=MeetingStatus.READY,
        source_type=SourceType.MANUAL,
        language="pt",
        started_at="2026-09-24T09:30:00Z",
        ended_at="2026-09-24T10:00:00Z",
        duration_ms=1_800_000,
        created_at="2026-09-24T09:30:00Z",
        updated_at="2026-09-24T10:00:00Z",
        client_name="A classificar",
        project_name="Projeto teste",
    )


def _recording(meeting: Meeting, role: str, audio_path: Path, recording_id: int) -> Recording:
    return Recording(
        id=recording_id,
        meeting_id=meeting.id,
        role=role,
        local_path=str(audio_path),
        original_filename=audio_path.name,
        media_type="audio/wav",
        size_bytes=audio_path.stat().st_size,
        duration_ms=1000,
        sample_rate=48000,
        channels=1,
        sha256="source-hash",
        metadata={"sample": True},
        created_at="2026-09-24T10:00:00Z",
    )


def test_export_is_repeatable_and_has_hashes_and_separate_tracks(tmp_path: Path) -> None:
    meeting = replace(_meeting(), description="Decisão: enviar a proposta na sexta-feira.")
    local = tmp_path / "private" / meeting.uuid
    local.mkdir(parents=True)
    root = tmp_path / "OneDrive" / "Meetings"
    audio_paths = []
    for name in ("mix.wav", "mic.wav", "system.wav"):
        path = local / name
        with wave.open(str(path), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(48000)
            audio.writeframes(b"\0\0" * 24)
        audio_paths.append(path)

    recordings = [
        _recording(meeting, "original", audio_paths[0], 1),
        _recording(meeting, "master_microphone", audio_paths[1], 2),
        _recording(meeting, "master_system", audio_paths[2], 3),
    ]
    transcription = Transcription(
        id=3,
        meeting_id=meeting.id,
        title="Call do cliente",
        engine="openai-compatible-audio",
        model="simulado",
        language="pt",
        status="completed",
        is_active=True,
        created_at="2026-09-24T10:00:00Z",
        completed_at="2026-09-24T10:01:00Z",
        settings={"source_recording_id": 1},
        segment_count=1,
    )
    segments = [
        TranscriptSegment(
            id=1,
            transcription_id=3,
            segment_index=0,
            start_ms=0,
            end_ms=0,
            text="Bom dia, começando a reunião.",
            speaker_id=None,
            confidence=None,
            is_final=True,
            metadata={"timestamp_quality": "unavailable"},
        )
    ]

    first = export_meeting_bundle(
        meeting=meeting,
        recordings=recordings,
        transcription=transcription,
        segments=segments,
        export_root=root,
    )
    second = export_meeting_bundle(
        meeting=meeting,
        recordings=recordings,
        transcription=transcription,
        segments=segments,
        export_root=root,
    )
    destination = Path(first["path"])
    assert first == second
    assert first["audio_files"] == 3
    assert sorted(path.name for path in (destination / "audio").iterdir()) == [
        "master-microphone-2.wav",
        "master-system-3.wav",
        "original-1.wav",
    ]
    manifest = json.loads((destination / "integrity.json").read_text(encoding="utf-8"))
    for name, digest in manifest["files"].items():
        assert hashlib.sha256((destination / name).read_bytes()).hexdigest() == digest
    markdown = (destination / "meeting.md").read_text(encoding="utf-8")
    assert markdown.index("## Anotações") < markdown.index("## Transcrição")
    assert "Decisão: enviar a proposta" in markdown
    assert "A transcrição inicial usa o mix" in markdown
    assert "`00:00:00.000`" not in markdown
    metadata = json.loads((destination / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["meeting"]["client"] == "A classificar"
    assert metadata["onedrive_sync_state"] == "not_verified"


def test_live_capture_export_fails_when_a_master_is_missing(tmp_path: Path) -> None:
    meeting = _meeting()
    original = tmp_path / "mix.wav"
    with wave.open(str(original), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(48000)
        audio.writeframes(b"\0\0" * 24)
    recording = _recording(meeting, "original", original, 1)
    recording.metadata["capture_source_id"] = "mic-device"

    with pytest.raises(ValueError, match="master_microphone, master_system"):
        export_meeting_bundle(
            meeting=meeting,
            recordings=[recording],
            transcription=None,
            segments=[],
            export_root=tmp_path / "OneDrive",
        )


def test_export_preserves_multiple_recordings_with_same_role(tmp_path: Path) -> None:
    meeting = _meeting()
    recordings = []
    for recording_id in (1, 2):
        path = tmp_path / f"audio-{recording_id}.wav"
        with wave.open(str(path), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(48000)
            audio.writeframes(bytes([recording_id, 0]) * 24)
        recordings.append(_recording(meeting, "original", path, recording_id))

    result = export_meeting_bundle(
        meeting=meeting,
        recordings=recordings,
        transcription=None,
        segments=[],
        export_root=tmp_path / "OneDrive",
    )
    audio_files = sorted(path.name for path in (Path(result["path"]) / "audio").iterdir())
    assert audio_files == ["original-1.wav", "original-2.wav"]
    metadata = json.loads((Path(result["path"]) / "metadata.json").read_text(encoding="utf-8"))
    assert [item["recording_id"] for item in metadata["audio"]] == [1, 2]
