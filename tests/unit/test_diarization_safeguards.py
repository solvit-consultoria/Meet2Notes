from __future__ import annotations

import pytest

from local_meeting_ai.application.ai_services import validate_diarization_speakers
from local_meeting_ai.domain.entities import DiarizationSegment
from local_meeting_ai.domain.errors import ValidationError


def _turns(speakers: int) -> list[DiarizationSegment]:
    return [
        DiarizationSegment(start_ms=index, end_ms=index + 1, speaker=index)
        for index in range(speakers)
    ]


def test_diarization_accepts_a_plausible_expected_count() -> None:
    assert validate_diarization_speakers(_turns(2), expected_speaker_count=2) == 2


def test_diarization_rejects_more_speakers_than_user_expected() -> None:
    with pytest.raises(ValidationError, match="No transcript labels were changed"):
        validate_diarization_speakers(_turns(3), expected_speaker_count=2)


def test_diarization_rejects_runaway_speaker_count() -> None:
    with pytest.raises(ValidationError, match="above the safety limit of 20"):
        validate_diarization_speakers(_turns(104))
