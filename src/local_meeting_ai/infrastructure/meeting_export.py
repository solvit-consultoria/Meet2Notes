from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import unicodedata
from pathlib import Path
from typing import Any

from local_meeting_ai.domain.entities import Meeting, Recording, Transcription, TranscriptSegment


def export_meeting_bundle(
    *,
    meeting: Meeting,
    recordings: list[Recording],
    transcription: Transcription | None,
    segments: list[TranscriptSegment],
    export_root: Path,
) -> dict[str, Any]:
    """Write a repeatable Markdown, JSON and audio bundle outside app storage."""
    destination = _meeting_directory(export_root, meeting)
    root = export_root.resolve()
    if not destination.resolve(strict=False).is_relative_to(root):
        raise ValueError("The export destination escapes the configured export root.")
    destination.mkdir(parents=True, exist_ok=True)
    audio_directory = destination / "audio"
    audio_directory.mkdir(exist_ok=True)
    if not audio_directory.resolve().is_relative_to(root):
        raise ValueError("The audio export destination escapes the configured export root.")

    file_hashes: dict[str, str] = {}
    copied_audio: list[dict[str, Any]] = []
    allowed_roles = {"original", "master_microphone", "master_system"}
    expected_roles = {recording.role for recording in recordings if recording.role in allowed_roles}
    live_capture = any(
        recording.role == "original" and recording.metadata.get("capture_source_id")
        for recording in recordings
    )
    if live_capture:
        expected_roles.update({"original", "master_microphone", "master_system"})
    available_roles = {recording.role for recording in recordings}
    missing_roles = expected_roles - available_roles
    if missing_roles:
        raise ValueError(
            "Exportação incompleta: faltam gravações de " + ", ".join(sorted(missing_roles))
        )
    for recording in recordings:
        if recording.role not in allowed_roles:
            continue
        source = Path(recording.local_path).resolve()
        if not source.is_file():
            raise ValueError(
                f"Exportação incompleta: o áudio {recording.role} não está disponível."
            )
        suffix = source.suffix.lower()
        if suffix not in {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac"}:
            suffix = ".audio"
        name = f"{_slug(recording.role)}-{recording.id}{suffix}"
        target = audio_directory / name
        _copy_atomic(source, target)
        relative = target.relative_to(destination).as_posix()
        digest = _sha256(target)
        file_hashes[relative] = digest
        copied_audio.append(
            {
                "recording_id": recording.id,
                "role": recording.role,
                "file": relative,
                "sha256": digest,
                "size_bytes": target.stat().st_size,
                "duration_ms": recording.duration_ms,
                "sample_rate": recording.sample_rate,
                "channels": recording.channels,
                "capture": recording.metadata,
            }
        )

    ordered_segments = sorted(segments, key=lambda item: item.segment_index)
    segment_document = [
        {
            "index": segment.segment_index,
            "start_ms": segment.start_ms,
            "end_ms": segment.end_ms,
            "text": segment.text,
            "speaker_id": segment.speaker_id,
            "confidence": segment.confidence,
            "timestamp_quality": segment.metadata.get("timestamp_quality", "recorded"),
        }
        for segment in ordered_segments
    ]
    _write_json_atomic(destination / "segments.json", segment_document)
    file_hashes["segments.json"] = _sha256(destination / "segments.json")

    transcript_markdown = _render_markdown(meeting, transcription, ordered_segments)
    _write_text_atomic(destination / "meeting.md", transcript_markdown)
    file_hashes["meeting.md"] = _sha256(destination / "meeting.md")

    metadata = {
        "schema_version": 1,
        "meeting": {
            "id": meeting.id,
            "uuid": meeting.uuid,
            "title": meeting.title,
            "client": meeting.client_name,
            "project": meeting.project_name,
            "description": meeting.description,
            "language": meeting.language,
            "started_at": meeting.started_at,
            "ended_at": meeting.ended_at,
            "duration_ms": meeting.duration_ms,
            "created_at": meeting.created_at,
        },
        "transcription": (
            {
                "id": transcription.id,
                "engine": transcription.engine,
                "model": transcription.model,
                "language": transcription.language,
                "status": transcription.status,
                "created_at": transcription.created_at,
                "completed_at": transcription.completed_at,
                "settings": transcription.settings,
                "segment_count": transcription.segment_count,
            }
            if transcription
            else None
        ),
        "audio": copied_audio,
        "local_storage_state": "saved",
        "destination_copy_state": "copied",
        "onedrive_sync_state": "not_verified",
    }
    _write_json_atomic(destination / "metadata.json", metadata)
    file_hashes["metadata.json"] = _sha256(destination / "metadata.json")

    manifest = {
        "schema_version": 1,
        "meeting_uuid": meeting.uuid,
        "files": file_hashes,
        "algorithm": "sha256",
    }
    _write_json_atomic(destination / "integrity.json", manifest)
    return {
        "path": str(destination),
        "meeting_id": meeting.id,
        "meeting_uuid": meeting.uuid,
        "files": len(file_hashes) + 1,
        "audio_files": len(copied_audio),
        "destination_copy_state": "copied",
        "onedrive_sync_state": "not_verified",
    }


def _meeting_directory(export_root: Path, meeting: Meeting) -> Path:
    started = (meeting.started_at or meeting.created_at or "unknown")[:10]
    meeting_id = f"meeting-{meeting.uuid[:8]}"
    return (
        export_root.resolve()
        / _slug(meeting.client_name or "A classificar")
        / _slug(meeting.project_name or "A classificar")
        / f"{started}-{meeting_id}"
    )


def _slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    clean = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_text).strip("-").lower()
    return clean[:80] or "a-classificar"


def _render_markdown(
    meeting: Meeting,
    transcription: Transcription | None,
    segments: list[TranscriptSegment],
) -> str:
    date = meeting.started_at or meeting.created_at
    lines = [
        f"# {meeting.title}",
        "",
        f"- **Cliente:** {meeting.client_name}",
        f"- **Projeto:** {meeting.project_name}",
        f"- **Data:** {date}",
        f"- **Duração:** {meeting.duration_ms or 0} ms",
        f"- **ID:** `{meeting.uuid}`",
        "",
        "> A transcrição inicial usa o mix dos canais de microfone e sistema. "
        "Os nomes de falante não identificam qual canal originou cada fala.",
        "",
        "## Transcrição",
        "",
    ]
    if transcription is None or not segments:
        lines.append("_Ainda não há transcrição disponível._")
    else:
        lines.append(
            f"_Motor: {transcription.engine} · Modelo: {transcription.model} · "
            f"Idioma: {transcription.language or 'não identificado'}_"
        )
        lines.append("")
        for segment in segments:
            speaker = f"Falante {segment.speaker_id}" if segment.speaker_id else None
            label = f"**{speaker}:** " if speaker else ""
            quality = segment.metadata.get("timestamp_quality", "recorded")
            timestamp = (
                f"`~{_timestamp(segment.start_ms)}` "
                if quality == "approximate"
                else f"`{_timestamp(segment.start_ms)}` "
                if quality != "unavailable"
                else ""
            )
            lines.append(f"- {timestamp}{label}{segment.text.strip()}")
    return "\n".join(lines).rstrip() + "\n"


def _timestamp(milliseconds: int) -> str:
    milliseconds = max(0, milliseconds)
    hours, rest = divmod(milliseconds, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    seconds, millis = divmod(rest, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02}.{millis:03}"


def _copy_atomic(source: Path, target: Path) -> None:
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    os.close(descriptor)
    temp = Path(temp_name)
    try:
        shutil.copyfile(source, temp)
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)


def _write_text_atomic(target: Path, content: str) -> None:
    _write_bytes_atomic(target, content.encode("utf-8"))


def _write_json_atomic(target: Path, content: Any) -> None:
    _write_text_atomic(target, json.dumps(content, ensure_ascii=False, indent=2) + "\n")


def _write_bytes_atomic(target: Path, content: bytes) -> None:
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    temp = Path(temp_name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
