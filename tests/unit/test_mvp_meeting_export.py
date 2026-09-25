from __future__ import annotations

import wave
from dataclasses import replace
from pathlib import Path

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


def test_export_is_repeatable_as_one_markdown_with_summary_first(tmp_path: Path) -> None:
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
            speaker_id=1,
            confidence=None,
            is_final=True,
            metadata={"timestamp_quality": "recorded"},
        ),
        TranscriptSegment(
            id=2,
            transcription_id=3,
            segment_index=1,
            start_ms=500,
            end_ms=900,
            text="Esta fala entra no mesmo parágrafo.",
            speaker_id=1,
            confidence=None,
            is_final=True,
            metadata={"timestamp_quality": "recorded"},
        ),
    ]

    first = export_meeting_bundle(
        meeting=meeting,
        recordings=recordings,
        transcription=transcription,
        segments=segments,
        export_root=root,
        summary_markdown="## Decisão\n\nEnviar a proposta.",
        speaker_names={1: "Rafa"},
    )
    second = export_meeting_bundle(
        meeting=meeting,
        recordings=recordings,
        transcription=transcription,
        segments=segments,
        export_root=root,
        summary_markdown="## Decisão\n\nEnviar a proposta.",
        speaker_names={1: "Rafa"},
    )
    destination = Path(first["path"])
    assert first == second
    assert first["files"] == 1
    assert first["audio_files"] == 0
    assert first["local_audio_state"] == "preserved_in_app_storage"
    assert [path.name for path in destination.iterdir()] == ["meeting.md"]
    assert all(path.is_file() for path in audio_paths)
    markdown = (destination / "meeting.md").read_text(encoding="utf-8")
    assert markdown.index("## Resumo") < markdown.index("## Transcrição")
    assert markdown.index("## Anotações") < markdown.index("## Transcrição")
    assert "Decisão: enviar a proposta" in markdown
    assert "Enviar a proposta." in markdown
    assert "**Rafa**" in markdown
    assert "Esta fala entra no mesmo parágrafo." in markdown
    assert "- `" not in markdown
    assert "`00:00:00.000`" in markdown


def test_markdown_export_does_not_copy_audio_masters(tmp_path: Path) -> None:
    meeting = _meeting()
    original = tmp_path / "mix.wav"
    with wave.open(str(original), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(48000)
        audio.writeframes(b"\0\0" * 24)
    recording = _recording(meeting, "original", original, 1)
    recording.metadata["capture_source_id"] = "mic-device"

    result = export_meeting_bundle(
        meeting=meeting,
        recordings=[recording],
        transcription=None,
        segments=[],
        export_root=tmp_path / "OneDrive",
    )
    assert Path(result["file"]).is_file()
    assert Path(recording.local_path).is_file()
    assert result["audio_files"] == 0


def test_export_keeps_multiple_local_recordings_out_of_markdown_folder(tmp_path: Path) -> None:
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
    assert sorted(path.name for path in Path(result["path"]).iterdir()) == ["meeting.md"]
    assert all(Path(recording.local_path).is_file() for recording in recordings)
