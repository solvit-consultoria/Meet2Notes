from __future__ import annotations

import asyncio
import io
import shutil
import threading
import time
import wave
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from local_meeting_ai.api.app import create_app
from local_meeting_ai.application.ai_services import (
    resolve_transcription_normalized,
    select_synchronized_masters,
)
from local_meeting_ai.config import AppSettings
from local_meeting_ai.domain.entities import (
    DiarizationSegment,
    MediaProbe,
    Recording,
    SegmentDraft,
    TranscriptionEngineRequest,
    TranscriptionResult,
)
from local_meeting_ai.domain.errors import JobCancelledError
from local_meeting_ai.domain.protocols import (
    CancellationCheck,
    ProgressReporter,
    SegmentReporter,
)


class FakeNormalizer:
    async def normalize_for_transcription(
        self,
        source: Path,
        destination: Path,
        *,
        sample_rate: int = 16000,
        channels: int = 1,
        is_cancelled: CancellationCheck | None = None,
    ) -> MediaProbe:
        if is_cancelled and is_cancelled():
            raise RuntimeError("cancelled")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        await asyncio.sleep(0)
        return MediaProbe(
            format_name="wav",
            duration_ms=100,
            size_bytes=destination.stat().st_size,
            sample_rate=sample_rate,
            channels=channels,
            has_audio=True,
            has_video=False,
            metadata={"format": "wav"},
        )


class FakeTranscriptionEngine:
    name = "fake-whisper"

    def capability(self) -> dict[str, Any]:
        return {
            "engine": self.name,
            "available": True,
            "cuda_available": False,
            "installed_models": ["small"],
        }

    async def prepare(
        self,
        profile: Any,
        *,
        allow_model_download: bool,
    ) -> None:
        del profile, allow_model_download
        await asyncio.sleep(0)

    async def transcribe(
        self,
        request: TranscriptionEngineRequest,
        progress: ProgressReporter,
        is_cancelled: CancellationCheck,
        segment_ready: SegmentReporter,
    ) -> TranscriptionResult:
        assert request.audio_path.suffix == ".wav"
        assert request.compute_type == "int8"
        drafts = [
            SegmentDraft(
                index=0,
                start_ms=0,
                end_ms=1200,
                text="Welcome to the product review.",
                confidence=0.94,
            ),
            SegmentDraft(
                index=1,
                start_ms=1200,
                end_ms=2800,
                text="We approved the product launch.",
                confidence=0.91,
            ),
        ]
        for index, segment in enumerate(drafts):
            assert not is_cancelled()
            segment_ready(segment)
            progress((index + 1) / len(drafts), f"Segment {index + 1}")
            await asyncio.sleep(0)
        return TranscriptionResult(
            language="en",
            language_probability=0.99,
            duration_ms=2800,
            segments=drafts,
        )

    def shutdown(self) -> None:
        return None

    def unload(self) -> None:
        return None


class CompositeTranscriptionEngine(FakeTranscriptionEngine):
    async def transcribe(
        self,
        request: TranscriptionEngineRequest,
        progress: ProgressReporter,
        is_cancelled: CancellationCheck,
        segment_ready: SegmentReporter,
    ) -> TranscriptionResult:
        result = await super().transcribe(request, progress, is_cancelled, segment_ready)
        return TranscriptionResult(
            language=result.language,
            language_probability=result.language_probability,
            duration_ms=result.duration_ms,
            segments=result.segments,
            speaker_turns=[
                DiarizationSegment(start_ms=0, end_ms=1200, speaker=0),
                DiarizationSegment(start_ms=1200, end_ms=2800, speaker=1),
            ],
        )


class InterruptedTranscriptionEngine(FakeTranscriptionEngine):
    def __init__(self, *, wait_for_cancel: bool) -> None:
        self.wait_for_cancel = wait_for_cancel
        self.segments_emitted = threading.Event()

    async def transcribe(
        self,
        request: TranscriptionEngineRequest,
        progress: ProgressReporter,
        is_cancelled: CancellationCheck,
        segment_ready: SegmentReporter,
    ) -> TranscriptionResult:
        del request, progress
        for index, text in enumerate(("First partial sentence.", "Second partial sentence.")):
            segment_ready(
                SegmentDraft(
                    index=index,
                    start_ms=index * 1000,
                    end_ms=(index + 1) * 1000,
                    text=text,
                )
            )
        # Revisions from some engines should replace the same index, not duplicate it.
        segment_ready(
            SegmentDraft(
                index=1,
                start_ms=1000,
                end_ms=2000,
                text="Corrected second partial sentence.",
            )
        )
        self.segments_emitted.set()
        if self.wait_for_cancel:
            for _ in range(500):
                if is_cancelled():
                    raise JobCancelledError("Transcription was cancelled")
                await asyncio.sleep(0.01)
        raise RuntimeError("Simulated transcription failure")


def _wav_bytes() -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b"\x00\x00" * 1600)
    return buffer.getvalue()


@contextmanager
def _client(
    tmp_path: Path,
    engine: FakeTranscriptionEngine | None = None,
) -> Iterator[TestClient]:
    settings = AppSettings(
        data_dir=tmp_path / "transcription-data",
        testing=True,
        open_browser=False,
        log_level="WARNING",
    )
    with TestClient(
        create_app(
            settings,
            transcription_engine=engine or FakeTranscriptionEngine(),
            audio_normalizer=FakeNormalizer(),
        )
    ) as client:
        yield client


def _wait_for_job(client: TestClient, job_uuid: str) -> dict[str, Any]:
    for _ in range(100):
        job = client.get(f"/api/jobs/{job_uuid}").json()
        if job["status"] in {"completed", "failed", "cancelled"}:
            return job
        time.sleep(0.02)
    raise AssertionError("Job did not reach a terminal state")


def test_transcription_pipeline_editor_and_versions(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        meeting = client.post("/api/meetings", json={"title": "Product review"}).json()
        imported = client.post(
            f"/api/meetings/{meeting['id']}/import",
            files={"file": ("review.wav", _wav_bytes(), "audio/wav")},
        )
        assert imported.status_code == 202
        recording = imported.json()["recording"]

        profiles = client.get("/api/models/transcription")
        assert profiles.status_code == 200
        balanced = next(item for item in profiles.json() if item["id"] == "balanced")
        assert balanced["installed"] is True
        assert balanced["compute_type"] == "int8"

        started = client.post(
            f"/api/meetings/{meeting['id']}/transcriptions",
            json={"profile_id": "balanced", "language": "en"},
        )
        assert started.status_code == 202
        started_payload = started.json()
        terminal = _wait_for_job(client, started_payload["job"]["uuid"])
        assert terminal["status"] == "completed"
        assert terminal["result"]["segment_count"] == 2

        transcription_id = started_payload["transcription"]["id"]
        detail = client.get(f"/api/transcriptions/{transcription_id}")
        assert detail.status_code == 200
        assert detail.json()["transcription"]["is_active"] is True
        assert detail.json()["transcription"]["title"] == "Nova transcrição"
        assert [segment["text"] for segment in detail.json()["segments"]] == [
            "Welcome to the product review.",
            "We approved the product launch.",
        ]
        assert all(segment["is_final"] for segment in detail.json()["segments"])
        assert 'data-default-title="Nova transcrição 2"' in client.get("/").text

        renamed = client.patch(
            f"/api/transcriptions/{transcription_id}",
            json={"title": "Product launch decision"},
        )
        assert renamed.status_code == 200
        assert renamed.json()["title"] == "Product launch decision"
        assert client.get(f"/api/meetings/{meeting['id']}").json()["title"] == (
            "Product launch decision"
        )
        assert 'data-default-title="Nova transcrição"' in client.get("/").text

        first_segment = detail.json()["segments"][0]
        edited = client.patch(
            f"/api/transcript-segments/{first_segment['id']}",
            json={"text": "Welcome to the release review."},
        )
        assert edited.status_code == 200
        assert edited.json()["text"] == "Welcome to the release review."

        replaced = client.post(
            f"/api/transcriptions/{transcription_id}/find-replace",
            json={"find": "product", "replacement": "release", "case_sensitive": False},
        )
        assert replaced.status_code == 200
        assert replaced.json()["replacements"] == 1

        media = client.get(f"/api/recordings/{recording['id']}/media")
        assert media.status_code == 200
        assert media.content.startswith(b"RIFF")

        versions = client.get(f"/api/meetings/{meeting['id']}/transcriptions")
        assert versions.status_code == 200
        assert versions.json()[0]["segment_count"] == 2

        workspace = client.get(f"/?meeting={meeting['id']}")
        assert workspace.status_code == 200
        assert 'id="workspace-meeting-select"' not in workspace.text
        assert 'id="start-transcription"' in workspace.text
        assert 'id="transcription-dialog"' in workspace.text
        assert "Choose your audio source" in workspace.text
        assert "Import media" not in workspace.text
        assert 'href="/?new=1"' in workspace.text
        assert "New meeting" in workspace.text
        assert 'href="/prompt"' in workspace.text
        assert "Prompt" in workspace.text
        assert 'href="/settings"' in workspace.text
        assert "minimal-settings-link" not in workspace.text
        assert 'id="postprocess-dialog"' in workspace.text
        assert 'data-meeting-tab="transcript"' in workspace.text
        assert 'data-meeting-tab="speakers"' in workspace.text
        assert 'data-meeting-tab="intelligence"' in workspace.text
        assert 'data-meeting-tab="utilities"' in workspace.text
        assert 'id="speaker-rebuild-identification"' in workspace.text
        assert 'id="speaker-rebuild-dialog"' in workspace.text
        assert 'id="ai-toggle-view"' in workspace.text
        assert "Who spoke during the meeting" not in workspace.text
        assert "Use your meeting outside Meet2Notes" not in workspace.text
        assert 'id="export-dialog"' in workspace.text
        assert 'data-audio-export="mp3"' in workspace.text
        assert 'data-export-source="transcript" data-export-format="markdown"' in workspace.text
        assert 'data-export-source="notes" data-export-format="pdf"' not in workspace.text
        assert 'id="download-meeting-json"' in workspace.text

        library = client.get("/meetings")
        assert library.status_code == 200
        assert "Product launch decision" in library.text
        assert "Product review" not in library.text
        assert f'href="/?meeting={meeting["id"]}"' in library.text

        meeting_redirect = client.get(
            f"/meetings/{meeting['id']}",
            follow_redirects=False,
        )
        assert meeting_redirect.status_code == 307
        assert meeting_redirect.headers["location"] == f"/?meeting={meeting['id']}"


@pytest.mark.parametrize("wait_for_cancel", [False, True])
def test_partial_transcript_is_flushed_on_failure_or_cancellation(
    tmp_path: Path,
    wait_for_cancel: bool,
) -> None:
    engine = InterruptedTranscriptionEngine(wait_for_cancel=wait_for_cancel)
    with _client(tmp_path, engine) as client:
        meeting = client.post("/api/meetings", json={"title": "Partial transcript"}).json()
        client.post(
            f"/api/meetings/{meeting['id']}/import",
            files={"file": ("partial.wav", _wav_bytes(), "audio/wav")},
        )
        started = client.post(
            f"/api/meetings/{meeting['id']}/transcriptions",
            json={"profile_id": "balanced", "language": "en"},
        ).json()

        if wait_for_cancel:
            assert engine.segments_emitted.wait(timeout=5)
            client.post(f"/api/jobs/{started['job']['uuid']}/cancel")
        terminal = _wait_for_job(client, started["job"]["uuid"])
        assert terminal["status"] == ("cancelled" if wait_for_cancel else "failed")

        detail = client.get(f"/api/transcriptions/{started['transcription']['id']}").json()
        assert [segment["text"] for segment in detail["segments"]] == [
            "First partial sentence.",
            "Corrected second partial sentence.",
        ]
        assert all(not segment["is_final"] for segment in detail["segments"])


def test_meeting_audio_can_be_deleted_without_removing_transcript(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        meeting = client.post("/api/meetings", json={"title": "Keep the text"}).json()
        imported = client.post(
            f"/api/meetings/{meeting['id']}/import",
            files={"file": ("private.wav", _wav_bytes(), "audio/wav")},
        ).json()
        _wait_for_job(client, imported["job"]["uuid"])
        started = client.post(
            f"/api/meetings/{meeting['id']}/transcriptions",
            json={"profile_id": "balanced", "language": "en"},
        ).json()
        _wait_for_job(client, started["job"]["uuid"])

        recordings_before = client.get(
            f"/api/meetings/{meeting['id']}/recordings"
        ).json()
        assert {item["role"] for item in recordings_before} == {"original", "normalized"}

        deleted = client.delete(f"/api/meetings/{meeting['id']}/audio")

        assert deleted.status_code == 200
        assert deleted.json()["audio_deleted_at"]
        assert deleted.json()["audio_deleted_bytes"] > 0
        assert deleted.json()["recording_count"] == 0
        assert client.get(f"/api/meetings/{meeting['id']}/recordings").json() == []
        detail = client.get(
            f"/api/transcriptions/{started['transcription']['id']}"
        ).json()
        assert [segment["text"] for segment in detail["segments"]] == [
            "Welcome to the product review.",
            "We approved the product launch.",
        ]
        assert "Keep the text" in client.get("/meetings").text
        assert "Audio deleted" in client.get("/meetings").text


def test_model_download_requires_explicit_confirmation(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        meeting = client.post("/api/meetings", json={"title": "Download consent"}).json()
        client.post(
            f"/api/meetings/{meeting['id']}/import",
            files={"file": ("review.wav", _wav_bytes(), "audio/wav")},
        )

        blocked = client.post(
            f"/api/meetings/{meeting['id']}/transcriptions",
            json={"profile_id": "fast", "allow_model_download": False},
        )
        assert blocked.status_code == 409
        assert "Confirm the model download" in blocked.json()["detail"]

        confirmed = client.post(
            f"/api/meetings/{meeting['id']}/transcriptions",
            json={"profile_id": "fast", "allow_model_download": True},
        )
        assert confirmed.status_code == 202


def test_composite_asr_persists_integrated_speaker_turns(tmp_path: Path) -> None:
    with _client(tmp_path, CompositeTranscriptionEngine()) as client:
        meeting = client.post("/api/meetings", json={"title": "Composite ASR"}).json()
        client.post(
            f"/api/meetings/{meeting['id']}/import",
            files={"file": ("composite.wav", _wav_bytes(), "audio/wav")},
        )
        started = client.post(
            f"/api/meetings/{meeting['id']}/transcriptions",
            json={"profile_id": "balanced", "language": "en"},
        ).json()

        terminal = _wait_for_job(client, started["job"]["uuid"])
        detail = client.get(
            f"/api/transcriptions/{started['transcription']['id']}"
        ).json()

        assert terminal["result"]["speaker_count"] == 2
        assert terminal["result"]["assigned_segments"] == 2
        assert [segment["speaker_id"] is not None for segment in detail["segments"]] == [
            True,
            True,
        ]


def test_master_track_clusters_are_namespaced_and_ambiguous_segments_stay_unassigned(
    tmp_path: Path,
) -> None:
    with _client(tmp_path) as client:
        meeting = client.post("/api/meetings", json={"title": "Track attribution"}).json()
        client.post(
            f"/api/meetings/{meeting['id']}/import",
            files={"file": ("track-test.wav", _wav_bytes(), "audio/wav")},
        )
        started = client.post(
            f"/api/meetings/{meeting['id']}/transcriptions",
            json={"profile_id": "balanced", "language": "en"},
        ).json()
        assert _wait_for_job(client, started["job"]["uuid"])["status"] == "completed"
        transcription_id = started["transcription"]["id"]
        container = client.app.state.container

        turns = [
            DiarizationSegment(0, 1200, 0, "master_microphone"),
            DiarizationSegment(1200, 2800, 0, "master_system"),
            # Equal evidence from separate source namespaces is ambiguous.
            DiarizationSegment(1200, 2000, 1, "master_microphone"),
            DiarizationSegment(1200, 2000, 1, "master_system"),
        ]
        assigned = container.transcriptions.assign_diarization(
            meeting_id=meeting["id"], transcription_id=transcription_id,
            diarization=turns, minimum_overlap_ratio=0.15,
        )

        segments = container.transcriptions.segments(transcription_id)
        speakers = container.transcriptions.speakers_for_transcription(transcription_id)
        assert assigned == 2
        assert segments[0].speaker_id != segments[1].speaker_id
        assert segments[0].speaker_id is not None
        assert segments[1].speaker_id is not None
        assert {speaker.display_name for speaker in speakers} == {
            "Microfone — Falante 1", "Áudio do sistema — Falante 1",
            "Microfone — Falante 2", "Áudio do sistema — Falante 2",
        }

        microphone_speaker = next(
            speaker for speaker in speakers
            if speaker.stable_key == "diarization:master_microphone:0"
        )
        profile = container.speaker_profiles.create(
            name="Saved profile", sample_path=None
        )
        container.transcriptions.assign_diarization(
            meeting_id=meeting["id"], transcription_id=transcription_id,
            diarization=turns, minimum_overlap_ratio=0.15,
            recognized_profiles={("master_microphone", 0): profile},
        )
        matched = container.transcriptions.get_speaker(microphone_speaker.id)
        assert matched is not None and matched.display_name == "Saved profile"
        with container.database.read() as connection:
            profile_row = connection.execute(
                "SELECT profile_id FROM speakers WHERE id = ?",
                (microphone_speaker.id,),
            ).fetchone()
        assert profile_row["profile_id"] == profile.id

        container.transcriptions.rename_speaker(microphone_speaker.id, "Manual name")
        container.transcriptions.assign_diarization(
            meeting_id=meeting["id"], transcription_id=transcription_id,
            diarization=turns, minimum_overlap_ratio=0.15,
            recognized_profiles={("master_microphone", 0): profile},
        )
        manually_named = container.transcriptions.get_speaker(microphone_speaker.id)
        assert manually_named is not None and manually_named.display_name == "Manual name"

        # Reprocessing with equal evidence across sources clears stale labels.
        container.transcriptions.assign_diarization(
            meeting_id=meeting["id"], transcription_id=transcription_id,
            diarization=[
                DiarizationSegment(0, 1200, 0, "master_microphone"),
                DiarizationSegment(1200, 2000, 0, "master_microphone"),
                DiarizationSegment(2000, 2800, 0, "master_system"),
            ], minimum_overlap_ratio=0.15,
        )
        segments = container.transcriptions.segments(transcription_id)
        assert segments[0].speaker_id is not None
        assert segments[1].speaker_id is None

        # Legacy mono turns retain the former max-overlap tie behavior.
        container.transcriptions.assign_diarization(
            meeting_id=meeting["id"], transcription_id=transcription_id,
            diarization=[
                DiarizationSegment(0, 1200, 0),
                DiarizationSegment(0, 1200, 1),
            ], minimum_overlap_ratio=0.15,
        )
        assert container.transcriptions.segments(transcription_id)[0].speaker_id is not None


def test_master_selection_follows_the_requested_transcription_source(
    tmp_path: Path,
) -> None:
    with _client(tmp_path) as client:
        meeting = client.post("/api/meetings", json={"title": "Two audio sources"}).json()
        transcription_ids: list[int] = []
        for index in range(2):
            imported = client.post(
                f"/api/meetings/{meeting['id']}/import",
                files={"file": (f"source-{index}.wav", _wav_bytes(), "audio/wav")},
            ).json()
            assert _wait_for_job(client, imported["job"]["uuid"])["status"] == "completed"
            started = client.post(
                f"/api/meetings/{meeting['id']}/transcriptions",
                json={"profile_id": "balanced", "language": "en"},
            ).json()
            assert _wait_for_job(client, started["job"]["uuid"])["status"] == "completed"
            transcription_ids.append(started["transcription"]["id"])

        container = client.app.state.container
        normalized = resolve_transcription_normalized(
            transcription_ids[0], meeting["id"],
            container.jobs, container.recordings,
        )
        latest_normalized = container.recordings.latest_for_role(meeting["id"], "normalized")
        assert latest_normalized is not None and latest_normalized.id != normalized.id
        source_id = normalized.metadata["source_recording_id"]
        source = container.recordings.get(source_id)
        assert source is not None

        masters = [
            Recording(
                id=900 + index, meeting_id=meeting["id"], role=role,
                local_path=source.local_path, original_filename=None,
                media_type="audio/wav", size_bytes=source.size_bytes,
                duration_ms=normalized.duration_ms, sample_rate=48000,
                channels=1, sha256=None,
                metadata={"synchronized_with_recording_id": source.id},
                created_at="later",
            )
            for index, role in enumerate(("master_microphone", "master_system"))
        ]
        selected = select_synchronized_masters(
            normalized, container.recordings.list_for_meeting(meeting["id"]) + masters
        )
        assert [item.metadata["synchronized_with_recording_id"] for item in selected] == [
            source_id, source_id,
        ]
