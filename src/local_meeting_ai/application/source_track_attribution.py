"""Conservative, read-only attribution preview for explicitly confirmed 1:1 calls.

This does not perform diarization and never writes speaker labels. It uses the
recorded microphone/system source roles and transcript timestamps to propose a
speaker label only when one source has clearly dominant activity.
"""

from __future__ import annotations

import hashlib
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

FRAME_MS = 20
CHUNK_SECONDS = 2
MAX_DURATION_MS = 4 * 60 * 60 * 1000
MAX_FILE_BYTES = 2 * 1024 * 1024 * 1024
MAX_TRACK_DURATION_DELTA_MS = 250
MIN_ACTIVE_WINDOWS = 3
MIN_SOURCE_SHARE = 0.82
MAX_OVERLAP_SHARE = 0.10
MIN_CONFIDENCE = 0.82
MIN_RMS_DBFS = -45.0


@dataclass(frozen=True, slots=True)
class TrackAnalysis:
    active: bytearray
    duration_ms: int
    sample_rate: int


def resolve_capture_master_pair(
    *, source_recording: Any, recordings: list[Any], meeting_id: int
) -> tuple[Any, Any] | None:
    """Resolve a verified microphone/system master pair for one original.

    Older capture manifests may omit ``capture_sources`` on the original. The
    per-track role, source kind, meeting ownership, and synchronized source ID
    remain required and provide the provenance in that legacy schema.
    """
    if (
        source_recording is None
        or source_recording.meeting_id != meeting_id
        or source_recording.role != "original"
    ):
        return None
    manifest_sources = source_recording.metadata.get("capture_sources")
    if isinstance(manifest_sources, list):
        manifest_kinds = {
            str(item.get("kind")) for item in manifest_sources if isinstance(item, dict)
        }
        if not {"microphone", "system"}.issubset(manifest_kinds):
            return None

    def matching_master(kind: str) -> Any | None:
        role = f"master_{kind}"
        matches = [
            recording
            for recording in recordings
            if recording.meeting_id == meeting_id
            and recording.role == role
            and recording.metadata.get("synchronized_with_recording_id")
            == source_recording.id
            and recording.metadata.get("capture_source_kind") == kind
        ]
        return matches[-1] if matches else None

    microphone = matching_master("microphone")
    system = matching_master("system")
    if microphone is None or system is None:
        return None
    return microphone, system


def preview_source_track_attribution(
    *,
    segments: list[Any],
    microphone_path: Path,
    system_path: Path,
    microphone_sha256: str,
    system_sha256: str,
    microphone_duration_ms: int | None,
    system_duration_ms: int | None,
    microphone_sync_id: int | None,
    system_sync_id: int | None,
    confirm_one_to_one: bool,
    speaker_count: int,
    confirm_mapping: bool,
    microphone_speaker: str,
    system_speaker: str,
) -> dict[str, Any]:
    """Return candidate labels without changing transcripts or meeting data.

    Every precondition is explicit. If the WAVs are not verifiably the aligned
    microphone/system masters, or their integrity/durations disagree, every
    segment is returned as unknown with a reason.
    """
    if not confirm_one_to_one:
        raise ValueError("Confirm that this was a one-to-one call")
    if speaker_count != 2:
        raise ValueError("Source-track attribution only supports exactly 2 speakers")
    if not confirm_mapping:
        raise ValueError("Confirm the microphone and system speaker mapping")
    mic_label = microphone_speaker.strip()
    system_label = system_speaker.strip()
    if not mic_label or not system_label or mic_label.casefold() == system_label.casefold():
        raise ValueError("Choose two distinct speaker names for the source tracks")

    unknown_reason = _validate_track_pair(
        microphone_path=microphone_path,
        system_path=system_path,
        microphone_sha256=microphone_sha256,
        system_sha256=system_sha256,
        microphone_duration_ms=microphone_duration_ms,
        system_duration_ms=system_duration_ms,
        microphone_sync_id=microphone_sync_id,
        system_sync_id=system_sync_id,
    )
    if unknown_reason:
        return _unknown_result(segments, unknown_reason, mic_label, system_label)

    mic = _read_activity(microphone_path)
    system = _read_activity(system_path)
    if mic.sample_rate != system.sample_rate or mic.duration_ms != system.duration_ms:
        return _unknown_result(
            segments,
            "The source WAV tracks are not aligned in sample rate and duration.",
            mic_label,
            system_label,
        )

    rows: list[dict[str, Any]] = []
    frame_ms = FRAME_MS
    for segment in segments:
        start_ms = max(0, int(segment.start_ms))
        end_ms = min(mic.duration_ms, int(segment.end_ms))
        if end_ms <= start_ms:
            rows.append(
                _unknown_segment(segment, "Transcript timestamp is outside the source audio.")
            )
            continue
        start = start_ms // frame_ms
        end = min(len(mic.active), (end_ms + frame_ms - 1) // frame_ms)
        mic_only = system_only = overlap = 0
        for index in range(start, end):
            mic_on = bool(mic.active[index])
            sys_on = bool(system.active[index])
            if mic_on and sys_on:
                overlap += 1
            elif mic_on:
                mic_only += 1
            elif sys_on:
                system_only += 1
        exclusive = mic_only + system_only
        active = exclusive + overlap
        if active == 0:
            rows.append(
                _unknown_segment(
                    segment, "No clear isolated source activity in this transcript interval."
                )
            )
            continue
        overlap_share = overlap / active
        if overlap_share > MAX_OVERLAP_SHARE:
            rows.append(
                _unknown_segment(
                    segment, "Both sources are active together; speaker is uncertain."
                )
            )
            continue
        if exclusive < MIN_ACTIVE_WINDOWS:
            rows.append(
                _unknown_segment(
                    segment, "No clear isolated source activity in this transcript interval."
                )
            )
            continue
        mic_share = mic_only / exclusive
        system_share = system_only / exclusive
        if max(mic_share, system_share) < MIN_SOURCE_SHARE:
            rows.append(
                _unknown_segment(segment, "The interval contains activity from both speakers.")
            )
            continue
        source_role, label, confidence = (
            ("master_microphone", mic_label, mic_share)
            if mic_share > system_share
            else ("master_system", system_label, system_share)
        )
        confidence *= 1.0 - overlap_share
        if confidence < MIN_CONFIDENCE:
            rows.append(
                _unknown_segment(segment, "Source evidence is below the confidence threshold.")
            )
            continue
        rows.append(
            {
                "segment_index": int(segment.segment_index),
                "start_ms": start_ms,
                "end_ms": end_ms,
                "speaker": label,
                "source_role": source_role,
                "confidence": round(confidence, 3),
                "reason": None,
            }
        )
    return {
        "mode": "experimental_source_activity_preview",
        "persisted": False,
        "speaker_count": 2,
        "mapping": {"master_microphone": mic_label, "master_system": system_label},
        "segments": rows,
    }


def _validate_track_pair(
    *,
    microphone_path: Path,
    system_path: Path,
    microphone_sha256: str,
    system_sha256: str,
    microphone_duration_ms: int | None,
    system_duration_ms: int | None,
    microphone_sync_id: int | None,
    system_sync_id: int | None,
) -> str | None:
    if microphone_sync_id is None or microphone_sync_id != system_sync_id:
        return "The microphone and system tracks do not share a verified capture source."
    if (
        microphone_duration_ms is None
        or system_duration_ms is None
        or microphone_duration_ms <= 0
        or system_duration_ms <= 0
        or microphone_duration_ms > MAX_DURATION_MS
        or system_duration_ms > MAX_DURATION_MS
        or abs(microphone_duration_ms - system_duration_ms) > MAX_TRACK_DURATION_DELTA_MS
    ):
        return "The source track durations do not match; attribution is unknown."
    for path, expected_hash in (
        (microphone_path, microphone_sha256),
        (system_path, system_sha256),
    ):
        if not expected_hash or not path.is_file():
            return "A source track is missing its integrity record or file."
        if path.stat().st_size > MAX_FILE_BYTES:
            return "Source track exceeds the safe analysis size limit."
        if _sha256(path) != expected_hash:
            return "A source track hash changed; attribution is unknown."
    try:
        mic_duration = _wav_duration_ms(microphone_path)
        system_duration = _wav_duration_ms(system_path)
    except (OSError, wave.Error, EOFError):
        return "The source tracks are not readable PCM WAV files."
    if (
        mic_duration <= 0
        or system_duration <= 0
        or mic_duration > MAX_DURATION_MS
        or system_duration > MAX_DURATION_MS
        or abs(mic_duration - system_duration) > MAX_TRACK_DURATION_DELTA_MS
        or abs(mic_duration - microphone_duration_ms) > MAX_TRACK_DURATION_DELTA_MS
        or abs(system_duration - system_duration_ms) > MAX_TRACK_DURATION_DELTA_MS
    ):
        return "The source track duration metadata does not match the WAV files."
    return None


def _read_activity(path: Path) -> TrackAnalysis:
    active = bytearray()
    with wave.open(str(path), "rb") as audio:
        channels = audio.getnchannels()
        rate = audio.getframerate()
        width = audio.getsampwidth()
        if width != 2 or channels not in (1, 2) or rate < 8000:
            raise wave.Error("Expected 16-bit mono or stereo PCM WAV")
        samples_per_window = max(1, round(rate * FRAME_MS / 1000))
        windows_per_chunk = CHUNK_SECONDS * 1000 // FRAME_MS
        frames_per_chunk = samples_per_window * windows_per_chunk
        threshold = 32768.0 * (10.0 ** (MIN_RMS_DBFS / 20.0))
        threshold_squared = threshold * threshold
        while True:
            raw = audio.readframes(frames_per_chunk)
            if not raw:
                break
            samples = np.frombuffer(raw, dtype="<i2")
            complete_values = (samples.size // channels) * channels
            samples = samples[:complete_values]
            complete_frames = samples.size // channels
            complete_windows = complete_frames // samples_per_window
            if complete_windows == 0:
                continue
            usable = complete_windows * samples_per_window * channels
            grouped = samples[:usable].reshape(complete_windows, samples_per_window, channels)
            squares = grouped.astype(np.float32, copy=False) ** 2
            energies = squares.mean(axis=(1, 2))
            active.extend((energies >= threshold_squared).astype(np.uint8).tobytes())
        duration_ms = round(audio.getnframes() * 1000 / rate)
    return TrackAnalysis(active, duration_ms, rate)


def _wav_duration_ms(path: Path) -> int:
    with wave.open(str(path), "rb") as audio:
        rate = audio.getframerate()
        if rate <= 0 or audio.getnchannels() not in (1, 2) or audio.getsampwidth() != 2:
            raise wave.Error("Expected 16-bit mono or stereo PCM WAV")
        return round(audio.getnframes() * 1000 / rate)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _unknown_result(
    segments: list[Any], reason: str, mic_label: str, system_label: str
) -> dict[str, Any]:
    return {
        "mode": "experimental_source_activity_preview",
        "persisted": False,
        "speaker_count": 2,
        "mapping": {"master_microphone": mic_label, "master_system": system_label},
        "warning": reason,
        "segments": [_unknown_segment(segment, reason) for segment in segments],
    }


def _unknown_segment(segment: Any, reason: str) -> dict[str, Any]:
    return {
        "segment_index": int(segment.segment_index),
        "start_ms": int(segment.start_ms),
        "end_ms": int(segment.end_ms),
        "speaker": None,
        "source_role": None,
        "confidence": 0.0,
        "reason": reason,
    }
