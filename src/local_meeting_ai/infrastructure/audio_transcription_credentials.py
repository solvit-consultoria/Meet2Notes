from __future__ import annotations

import importlib
import importlib.util
from typing import Any, cast

from local_meeting_ai.domain.errors import CapabilityUnavailableError

SERVICE_NAME = "Meet2Notes"
ACCOUNT_NAME = "mvp-audio-transcription"


class KeyringAudioTranscriptionCredentialStore:
    """Store the optional remote-ASR credential outside app settings and logs."""

    def configured(self) -> bool:
        if importlib.util.find_spec("keyring") is None:
            return False
        try:
            return bool(_keyring().get_password(SERVICE_NAME, ACCOUNT_NAME))
        except Exception:
            return False

    def get(self) -> str | None:
        if importlib.util.find_spec("keyring") is None:
            return None
        try:
            return cast(str | None, _keyring().get_password(SERVICE_NAME, ACCOUNT_NAME))
        except Exception:
            return None

    def set(self, value: str) -> None:
        if importlib.util.find_spec("keyring") is None:
            raise CapabilityUnavailableError(
                "Secure operating-system credential storage is unavailable."
            )
        if not value.strip():
            raise ValueError("The API key cannot be empty.")
        try:
            _keyring().set_password(SERVICE_NAME, ACCOUNT_NAME, value)
        except Exception as error:
            raise CapabilityUnavailableError(
                "The API key could not be stored in the operating-system credential manager."
            ) from error

    def delete(self) -> None:
        if importlib.util.find_spec("keyring") is None:
            return
        try:
            _keyring().delete_password(SERVICE_NAME, ACCOUNT_NAME)
        except Exception:
            return


def _keyring() -> Any:
    return importlib.import_module("keyring")
