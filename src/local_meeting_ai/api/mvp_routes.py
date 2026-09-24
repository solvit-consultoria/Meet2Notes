from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from local_meeting_ai.api.dependencies import get_container
from local_meeting_ai.api.schemas import TranscriptionResponse
from local_meeting_ai.bootstrap import Container
from local_meeting_ai.domain.errors import ValidationError
from local_meeting_ai.infrastructure.meeting_export import export_meeting_bundle

router = APIRouter(prefix="/api/mvp", tags=["meeting MVP"])
ContainerDependency = Annotated[Container, Depends(get_container)]


class MvpSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    export_root: str | None = Field(default=None, max_length=2048)
    audio_api_base_url: str = Field(default="", max_length=2048)
    audio_api_model: str = Field(default="", max_length=200)


class MvpExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_name: str | None = Field(default=None, max_length=120)
    project_name: str | None = Field(default=None, max_length=120)


class MvpApiKeyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_key: str = Field(min_length=1, max_length=4096)


class MvpApiTranscriptionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm_upload: bool = False


@router.get("/settings")
def mvp_settings(container: ContainerDependency) -> dict[str, Any]:
    values = container.preferences.get_all()
    return {
        "export_root": values.get("mvp_export_root", ""),
        "audio_api_base_url": values.get("mvp_audio_api_base_url", ""),
        "audio_api_model": values.get("mvp_audio_api_model", ""),
        "api_key_configured": _api_key_store().configured(),
    }


@router.put("/settings")
def update_mvp_settings(
    payload: MvpSettingsUpdate,
    container: ContainerDependency,
) -> dict[str, Any]:
    supplied = payload.model_dump(exclude_unset=True)
    values: dict[str, Any] = {}
    if "audio_api_base_url" in supplied:
        base_url = supplied["audio_api_base_url"].strip().rstrip("/")
        if base_url:
            from local_meeting_ai.adapters.transcription.openai_compatible_audio import (
                OpenAICompatibleAudioTranscriber,
            )

            try:
                OpenAICompatibleAudioTranscriber(base_url)
            except ValueError as error:
                raise ValidationError(str(error)) from error
        values["mvp_audio_api_base_url"] = base_url
    if "audio_api_model" in supplied:
        values["mvp_audio_api_model"] = supplied["audio_api_model"].strip()
    if payload.export_root is not None:
        values["mvp_export_root"] = _validated_export_root(payload.export_root, container)
    if values:
        container.preferences.update(values)
    return mvp_settings(container)


@router.put("/api-key")
def save_audio_api_key(payload: MvpApiKeyUpdate) -> dict[str, bool]:
    _api_key_store().set(payload.api_key)
    return {"configured": True}


@router.delete("/api-key")
def remove_audio_api_key() -> dict[str, bool]:
    _api_key_store().delete()
    return {"configured": False}


@router.post("/meetings/{meeting_id}/export")
def export_meeting(
    meeting_id: int,
    payload: MvpExportRequest,
    container: ContainerDependency,
) -> dict[str, Any]:
    meeting = container.meeting_service.get(meeting_id)
    changes = {
        key: value
        for key, value in {
            "client_name": payload.client_name,
            "project_name": payload.project_name,
        }.items()
        if value is not None
    }
    if changes:
        meeting = container.meeting_service.update(meeting_id, changes)

    settings = container.preferences.get_all()
    export_root = settings.get("mvp_export_root")
    if not isinstance(export_root, str) or not export_root.strip():
        raise ValidationError("Configure a pasta de exportação nas Configurações primeiro.")
    target_root = _validated_export_root(export_root, container)
    transcription = container.transcriptions.active_for_meeting(meeting_id)
    segments = container.transcriptions.segments(transcription.id) if transcription else []
    try:
        return export_meeting_bundle(
            meeting=meeting,
            recordings=container.recordings.list_for_meeting(meeting_id),
            transcription=transcription,
            segments=segments,
            export_root=target_root,
        )
    except ValueError as error:
        raise ValidationError(str(error)) from error


@router.post("/meetings/{meeting_id}/transcribe-api", response_model=TranscriptionResponse)
async def transcribe_with_api(
    meeting_id: int,
    payload: MvpApiTranscriptionRequest,
    container: ContainerDependency,
) -> TranscriptionResponse:
    if not payload.confirm_upload:
        raise ValidationError("Confirme explicitamente o envio do áudio antes de continuar.")
    meeting = container.meeting_service.get(meeting_id)
    preferences = container.preferences.get_all()
    base_url = str(preferences.get("mvp_audio_api_base_url") or "").strip()
    model = str(preferences.get("mvp_audio_api_model") or "").strip()
    credential = _api_key_store().get()
    if not base_url or not model or not credential:
        raise ValidationError("Configure o provedor e a chave da API nas Configurações.")
    audio = container.recordings.latest_for_role(meeting_id, "original")
    if audio is None or not Path(audio.local_path).is_file():
        raise ValidationError("Não há áudio local disponível para transcrever.")

    from local_meeting_ai.adapters.transcription.openai_compatible_audio import (
        OpenAICompatibleAudioTranscriber,
    )

    try:
        result = await OpenAICompatibleAudioTranscriber(base_url).transcribe(
            Path(audio.local_path),
            api_key=credential,
            model=model,
            language=meeting.language,
        )
    except Exception:
        # Provider exception bodies and request headers can contain secrets.
        raise ValidationError(
            "A transcrição pela API falhou. O áudio local foi preservado; "
            "confira a configuração e tente novamente manualmente."
        ) from None

    transcription = container.transcriptions.create(
        meeting_id=meeting.id,
        title=container.transcriptions.next_default_title(),
        engine="openai-compatible-audio",
        model=model,
        language=result.language or meeting.language,
        settings={
            "provider": "openai-compatible-audio",
            "base_url": base_url,
            "timestamp_source": "provider_response",
            "source_recording_id": audio.id,
        },
    )
    completed = container.transcriptions.complete(
        transcription.id,
        language=result.language or meeting.language,
        segments=result.segments,
    )
    if completed is None:
        raise ValidationError("A transcrição retornou, mas não pôde ser salva localmente.")
    return TranscriptionResponse.model_validate(completed)


def _validated_export_root(value: str, container: Container) -> Path:
    clean = value.strip()
    if not clean:
        raise ValidationError("Informe a pasta principal de exportação.")
    path = Path(clean).expanduser()
    if not path.is_absolute():
        raise ValidationError("A pasta de exportação precisa ser um caminho absoluto.")
    try:
        resolved = path.resolve(strict=False)
        app_root = container.paths.root.resolve(strict=False)
    except OSError as error:
        raise ValidationError("Não foi possível validar a pasta de exportação.") from error
    if (
        resolved == app_root
        or resolved.is_relative_to(app_root)
        or app_root.is_relative_to(resolved)
    ):
        raise ValidationError(
            "A pasta de exportação precisa ficar separada do armazenamento privado do app."
        )
    return resolved


def _api_key_store() -> Any:
    from local_meeting_ai.infrastructure.audio_transcription_credentials import (
        KeyringAudioTranscriptionCredentialStore,
    )

    return KeyringAudioTranscriptionCredentialStore()
