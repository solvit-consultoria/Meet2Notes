from __future__ import annotations

from pathlib import Path

from scripts.check_environment import (
    _discover_windows_media_tools,
    collect_environment_report,
)


def test_media_tools_are_discovered_from_winget_package_outside_path(tmp_path: Path) -> None:
    local_app_data = tmp_path / "LocalAppData"
    package = local_app_data / "Microsoft" / "WinGet" / "Packages" / "Gyan.FFmpeg_Test"
    package.mkdir(parents=True)
    (package / "ffmpeg.exe").touch()
    (package / "ffprobe.exe").touch()

    ffmpeg, ffprobe = _discover_windows_media_tools(local_app_data, None)

    assert ffmpeg == str(package / "ffmpeg.exe")
    assert ffprobe == str(package / "ffprobe.exe")


def test_model_check_accepts_hugging_face_cache_layout(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "scripts.check_environment.shutil.which", lambda name: f"C:/tools/{name}.exe"
    )
    monkeypatch.setattr(
        "scripts.check_environment.importlib.util.find_spec",
        lambda name: object() if name in {"faster_whisper", "sherpa_onnx"} else None,
    )
    cached_model = (
        tmp_path / "models--Systran--faster-whisper-small" / "snapshots" / "test-snapshot"
    )
    cached_model.mkdir(parents=True)
    (cached_model / "model.bin").touch()
    (cached_model / "config.json").touch()

    report = collect_environment_report(models_dir=tmp_path, require_whisper_model="small")

    assert report["ready"] is True
    assert report["checks"]["media_tools"]["status"] == "ready"
    assert report["checks"]["transcription_model"]["status"] == "ready"
    assert report["checks"]["diarization_runtime"]["status"] == "ready"
    assert report["checks"]["local_summary_runtime"]["status"] == "optional-missing"


def test_readiness_fails_when_required_media_tools_or_model_are_missing(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "scripts.check_environment.shutil.which",
        lambda name: f"C:/tools/{name}.exe" if name == "ffmpeg" else None,
    )
    monkeypatch.setattr(
        "scripts.check_environment.importlib.util.find_spec",
        lambda name: object() if name == "faster_whisper" else None,
    )
    monkeypatch.setattr(
        "scripts.check_environment._discover_windows_media_tools",
        lambda *_args: (None, None),
    )

    report = collect_environment_report(models_dir=tmp_path, require_whisper_model="small")

    assert report["ready"] is False
    assert report["errors"] == ["media_tools", "transcription_model"]
    assert report["checks"]["local_summary_runtime"]["status"] == "optional-missing"


def test_skip_media_tools_is_reported_as_optional_but_does_not_hide_model_failure(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr("scripts.check_environment.shutil.which", lambda _name: None)
    monkeypatch.setattr(
        "scripts.check_environment.importlib.util.find_spec",
        lambda name: object() if name == "faster_whisper" else None,
    )
    monkeypatch.setattr(
        "scripts.check_environment._discover_windows_media_tools",
        lambda *_args: (None, None),
    )

    report = collect_environment_report(
        models_dir=tmp_path,
        require_whisper_model="small",
        allow_missing_media_tools=True,
    )

    assert report["ready"] is False
    assert report["errors"] == ["transcription_model"]
    assert report["checks"]["media_tools"]["status"] == "optional-missing"
