"""Explicit OpenAI Audio-compatible transcription adapter.

The caller supplies the credential for each invocation. This module neither
stores credentials nor performs requests during construction/import.
"""

from __future__ import annotations

import ipaddress
import math
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from local_meeting_ai.domain.entities import SegmentDraft, TranscriptionResult


class OpenAICompatibleTranscriptionError(RuntimeError):
    """Sanitized provider failure that never includes request or response data."""


class OpenAICompatibleAudioTranscriber:
    """Send one audio file to a compatible ``audio/transcriptions`` endpoint."""

    def __init__(
        self,
        base_url: str,
        *,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 300,
    ) -> None:
        self._endpoint = _transcriptions_endpoint(base_url)
        self._client = client
        self._timeout_seconds = timeout_seconds

    async def transcribe(
        self,
        audio_path: Path,
        *,
        api_key: str,
        model: str,
        language: str | None = None,
    ) -> TranscriptionResult:
        """Transcribe only when called; the key is used only in this request."""
        if not api_key.strip():
            raise ValueError("An API key is required for this explicit request.")
        if not model.strip():
            raise ValueError("A transcription model is required.")

        fields = {"model": model, "response_format": "verbose_json"}
        if language:
            fields["language"] = language
        headers = {"Authorization": f"Bearer {api_key}"}

        try:
            with audio_path.open("rb") as audio_file:
                files = {"file": (audio_path.name, audio_file, "application/octet-stream")}
                if self._client is not None:
                    response = await self._client.post(
                        self._endpoint,
                        data=fields,
                        files=files,
                        headers=headers,
                        timeout=self._timeout_seconds,
                    )
                else:
                    async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                        response = await client.post(
                            self._endpoint,
                            data=fields,
                            files=files,
                            headers=headers,
                        )
        except (httpx.HTTPError, OSError):
            raise OpenAICompatibleTranscriptionError(
                "The transcription provider could not be reached."
            ) from None

        if response.is_error:
            raise OpenAICompatibleTranscriptionError(
                f"The transcription provider returned HTTP {response.status_code}."
            )
        try:
            payload = response.json()
        except (ValueError, TypeError):
            raise OpenAICompatibleTranscriptionError(
                "The transcription provider returned an invalid response."
            ) from None
        if not isinstance(payload, dict):
            raise OpenAICompatibleTranscriptionError(
                "The transcription provider returned an invalid response."
            )
        return _parse_result(payload)


def _transcriptions_endpoint(base_url: str) -> str:
    value = base_url.strip().rstrip("/")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("The provider URL must be an absolute HTTP or HTTPS URL.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("The provider URL must not contain credentials or query data.")
    if parsed.scheme == "http" and not _is_loopback(parsed.hostname):
        raise ValueError(
            "Provedores remotos precisam usar HTTPS; HTTP só é permitido em loopback."
        )
    if value.endswith("/audio/transcriptions"):
        return value
    return f"{value}/audio/transcriptions"


def _is_loopback(hostname: str | None) -> bool:
    if not hostname:
        return False
    if hostname.casefold() == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def _parse_result(payload: dict[str, Any]) -> TranscriptionResult:
    raw_segments = payload.get("segments")
    segments: list[SegmentDraft] = []
    if isinstance(raw_segments, list):
        for raw in raw_segments:
            if not isinstance(raw, dict) or not isinstance(raw.get("text"), str):
                continue
            start = _seconds_to_ms(raw.get("start"))
            end = _seconds_to_ms(raw.get("end"))
            timestamp_quality = (
                "precise" if start is not None and end is not None else "unavailable"
            )
            if start is None:
                start = 0
            if end is None:
                end = start
            if end < start:
                end = start
            segments.append(
                SegmentDraft(
                    index=len(segments),
                    start_ms=start,
                    end_ms=end,
                    text=raw["text"].strip(),
                    metadata={"timestamp_quality": timestamp_quality},
                )
            )

    duration_ms = _seconds_to_ms(payload.get("duration"))
    text = payload.get("text")
    if not segments and isinstance(text, str) and text.strip():
        # A whole-response transcript has no segment boundaries. Keep a single
        # displayable segment while explicitly marking its timing as approximate.
        segments.append(
            SegmentDraft(
                index=0,
                start_ms=0,
                end_ms=duration_ms or 0,
                text=text.strip(),
                metadata={
                    "timestamp_quality": "approximate" if duration_ms else "unavailable"
                },
            )
        )

    return TranscriptionResult(
        language=payload.get("language") if isinstance(payload.get("language"), str) else None,
        language_probability=None,
        duration_ms=duration_ms,
        segments=segments,
    )


def _seconds_to_ms(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value < 0:
        return None
    return round(value * 1000)
