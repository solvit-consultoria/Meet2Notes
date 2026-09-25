from __future__ import annotations

import json
import os
import re
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
    summary_markdown: str | None = None,
    speaker_names: dict[int, str] | None = None,
) -> dict[str, Any]:
    """Export a compact single Markdown file; originals remain in local app storage."""
    destination = _meeting_directory(export_root, meeting)
    root = export_root.resolve()
    if not destination.resolve(strict=False).is_relative_to(root):
        raise ValueError("The export destination escapes the configured export root.")
    destination.mkdir(parents=True, exist_ok=True)

    content = _render_markdown(
        meeting,
        transcription,
        sorted(segments, key=lambda item: item.segment_index),
        summary_markdown=summary_markdown,
        speaker_names=speaker_names or {},
    )
    target = destination / "meeting.md"
    _write_text_atomic(target, content)
    return {
        "path": str(destination),
        "file": str(target),
        "meeting_id": meeting.id,
        "meeting_uuid": meeting.uuid,
        "files": 1,
        "audio_files": 0,
        "local_audio_state": "preserved_in_app_storage" if recordings else "none",
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
    *,
    summary_markdown: str | None,
    speaker_names: dict[int, str],
) -> str:
    date = meeting.started_at or meeting.created_at
    lines = [
        "---",
        f"title: {json.dumps(meeting.title, ensure_ascii=False)}",
        f"client: {json.dumps(meeting.client_name, ensure_ascii=False)}",
        f"project: {json.dumps(meeting.project_name, ensure_ascii=False)}",
        f"date: {json.dumps(date, ensure_ascii=False)}",
        f"duration_ms: {meeting.duration_ms or 0}",
        f"meeting_id: {json.dumps(meeting.uuid)}",
        "language: "
        + json.dumps(transcription.language if transcription else meeting.language or ""),
        "---",
        "",
        f"# {meeting.title}",
        "",
        f"**Cliente:** {meeting.client_name}  ",
        f"**Projeto:** {meeting.project_name}  ",
        f"**Data:** {date}  ",
        f"**Duração:** {_duration(meeting.duration_ms or 0)}",
        "",
        "## Resumo",
        "",
        (
            summary_markdown
            or "_Resumo ainda não disponível. Gere as notas de IA no aplicativo._"
        ).strip(),
        "",
    ]
    if meeting.description and meeting.description.strip():
        lines.extend(["## Anotações", "", meeting.description.strip(), ""])
    lines.extend(["## Transcrição", ""])
    if transcription is None or not segments:
        lines.append("_Ainda não há transcrição disponível._")
    else:
        lines.extend([
            f"_Motor: {transcription.engine} · Modelo: {transcription.model} · "
            f"Idioma: {transcription.language or 'não identificado'}_",
            "",
        ])
        lines.extend(_conversation_paragraphs(segments, speaker_names))
    return "\n".join(lines).rstrip() + "\n"


def _conversation_paragraphs(
    segments: list[TranscriptSegment], speaker_names: dict[int, str]
) -> list[str]:
    groups: list[dict[str, Any]] = []
    for segment in segments:
        text = segment.text.strip()
        if not text:
            continue
        speaker_id = segment.speaker_id
        speaker = (
            speaker_names.get(speaker_id, f"Falante {speaker_id}")
            if speaker_id
            else "Falante pendente"
        )
        previous = groups[-1] if groups else None
        gap = segment.start_ms - previous["end_ms"] if previous else 0
        if (
            previous
            and previous["speaker"] == speaker
            and gap <= 3_000
            and previous["characters"] + len(text) <= 600
        ):
            previous["texts"].append(text)
            previous["end_ms"] = segment.end_ms
            previous["characters"] += len(text)
            continue
        groups.append({
            "speaker": speaker,
            "start_ms": segment.start_ms,
            "end_ms": segment.end_ms,
            "quality": segment.metadata.get("timestamp_quality", "recorded"),
            "texts": [text],
            "characters": len(text),
        })

    paragraphs = []
    for group in groups:
        quality = group["quality"]
        timestamp = (
            f"`~{_timestamp(group['start_ms'])}`"
            if quality == "approximate"
            else f"`{_timestamp(group['start_ms'])}`"
            if quality != "unavailable"
            else ""
        )
        heading = f"**{group['speaker']}**"
        if timestamp:
            heading += f" · {timestamp}"
        paragraphs.append(f"{heading}\n\n{' '.join(group['texts'])}")
    return paragraphs or ["_A transcrição não contém fala reconhecida._"]


def _duration(milliseconds: int) -> str:
    seconds = max(0, milliseconds // 1000)
    hours, rest = divmod(seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    return f"{hours}h {minutes:02}min" if hours else f"{minutes}min {seconds:02}s"


def _timestamp(milliseconds: int) -> str:
    milliseconds = max(0, milliseconds)
    hours, rest = divmod(milliseconds, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    seconds, millis = divmod(rest, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02}.{millis:03}"


def _write_text_atomic(target: Path, content: str) -> None:
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    temp = Path(temp_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)
