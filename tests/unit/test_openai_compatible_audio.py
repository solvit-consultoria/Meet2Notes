from __future__ import annotations

import httpx
import pytest

from local_meeting_ai.adapters.transcription.openai_compatible_audio import (
    OpenAICompatibleAudioTranscriber,
    OpenAICompatibleTranscriptionError,
)


@pytest.mark.asyncio
async def test_posts_multipart_verbose_json_and_parses_timestamped_segments(tmp_path):
    audio_path = tmp_path / "meeting.wav"
    audio_path.write_bytes(b"sample-audio")
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "text": "Olá.",
                "language": "pt",
                "duration": 1.25,
                "segments": [{"start": 0.2, "end": 0.8, "text": "Olá."}],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = OpenAICompatibleAudioTranscriber(
            "https://speech.example/v1", client=client
        )
        result = await adapter.transcribe(
            audio_path, api_key="test-secret", model="model-1", language="pt"
        )

    request = seen[0]
    body = request.content.decode("latin-1")
    assert request.url == "https://speech.example/v1/audio/transcriptions"
    assert request.headers["authorization"] == "Bearer test-secret"
    assert "name=\"response_format\"" in body and "verbose_json" in body
    assert "name=\"language\"" in body and "pt" in body
    assert "sample-audio" in body
    assert result.language == "pt"
    assert result.duration_ms == 1250
    assert [(s.start_ms, s.end_ms, s.text) for s in result.segments] == [(200, 800, "Olá.")]
    assert result.segments[0].metadata == {"timestamp_quality": "precise"}


@pytest.mark.asyncio
async def test_marks_text_only_response_timing_as_approximate_or_unavailable(tmp_path):
    audio_path = tmp_path / "meeting.wav"
    audio_path.write_bytes(b"audio")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"text": "Texto completo", "duration": 3.4})
        )
    ) as client:
        result = await OpenAICompatibleAudioTranscriber(
            "https://speech.example/v1", client=client
        ).transcribe(audio_path, api_key="secret", model="asr")

    assert len(result.segments) == 1
    assert result.segments[0].start_ms == 0
    assert result.segments[0].end_ms == 3400
    assert result.segments[0].metadata == {"timestamp_quality": "approximate"}

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"text": "Texto"}))
    ) as client:
        no_duration = await OpenAICompatibleAudioTranscriber(
            "https://speech.example/v1", client=client
        ).transcribe(audio_path, api_key="secret", model="asr")
    assert no_duration.segments[0].metadata == {"timestamp_quality": "unavailable"}


@pytest.mark.asyncio
async def test_provider_error_does_not_expose_key_or_response_body(tmp_path):
    audio_path = tmp_path / "meeting.wav"
    audio_path.write_bytes(b"audio")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(401, text="Bearer secret-token rejected")
        )
    ) as client:
        adapter = OpenAICompatibleAudioTranscriber(
            "https://speech.example/v1", client=client
        )
        with pytest.raises(OpenAICompatibleTranscriptionError) as error:
            await adapter.transcribe(audio_path, api_key="secret-token", model="asr")

    assert "401" in str(error.value)
    assert "secret-token" not in str(error.value)
    assert "rejected" not in str(error.value)


def test_rejects_urls_with_embedded_credentials_or_query_data():
    with pytest.raises(ValueError, match="must not contain credentials"):
        OpenAICompatibleAudioTranscriber("https://user:pass@speech.example/v1")
    with pytest.raises(ValueError, match="must not contain credentials"):
        OpenAICompatibleAudioTranscriber("https://speech.example/v1?token=secret")


def test_http_is_allowed_only_for_loopback_hosts():
    for url in ("http://speech.example/v1", "http://192.0.2.10/v1"):
        with pytest.raises(ValueError, match="precisam usar HTTPS"):
            OpenAICompatibleAudioTranscriber(url)

    for url in ("http://localhost:8080/v1", "http://127.0.0.1:8080/v1", "http://[::1]:8080/v1"):
        OpenAICompatibleAudioTranscriber(url)
