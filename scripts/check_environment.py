from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Any


def _discover_windows_media_tools(
    local_app_data: Path | None, program_files: Path | None
) -> tuple[str | None, str | None]:
    directories: list[Path] = []
    if local_app_data:
        links = local_app_data / "Microsoft" / "WinGet" / "Links"
        if links.is_dir():
            directories.append(links)
    package_roots = []
    if local_app_data:
        package_roots.append(local_app_data / "Microsoft" / "WinGet" / "Packages")
    if program_files:
        package_roots.append(program_files / "WinGet" / "Packages")
    for root in package_roots:
        if root.is_dir():
            for package in root.glob("Gyan.FFmpeg*"):
                directories.extend(executable.parent for executable in package.rglob("ffmpeg.exe"))
    for directory in directories:
        ffmpeg = directory / "ffmpeg.exe"
        ffprobe = directory / "ffprobe.exe"
        if ffmpeg.is_file() and ffprobe.is_file():
            return str(ffmpeg), str(ffprobe)
    return None, None


def _model_installed(models_dir: Path, model: str) -> bool:
    repositories = {
        "tiny": "Systran/faster-whisper-tiny",
        "base": "Systran/faster-whisper-base",
        "small": "Systran/faster-whisper-small",
        "medium": "Systran/faster-whisper-medium",
        "large-v3": "Systran/faster-whisper-large-v3",
        "distil-large-v3": "Systran/faster-distil-whisper-large-v3",
        "turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
    }
    repository = repositories[model]
    cache = models_dir / f"models--{repository.replace('/', '--')}"
    direct = models_dir / model
    candidates = [cache, direct]
    for candidate in candidates:
        if candidate.is_dir():
            model_files = list(candidate.rglob("model.bin"))
            config_files = list(candidate.rglob("config.json"))
            if model_files and config_files:
                return True
    return False


def _saved_models_directory(database_path: Path) -> Path | None:
    if not database_path.is_file():
        return None
    try:
        with sqlite3.connect(f"{database_path.resolve().as_uri()}?mode=ro", uri=True) as connection:
            row = connection.execute(
                "SELECT value_json FROM settings WHERE key = 'models_directory'"
            ).fetchone()
    except sqlite3.Error:
        return None
    if not row or not row[0]:
        return None
    try:
        value = json.loads(row[0])
    except (TypeError, json.JSONDecodeError):
        return None
    return Path(value).expanduser() if isinstance(value, str) and value.strip() else None


def collect_environment_report(
    *,
    models_dir: Path | None = None,
    require_whisper_model: str | None = None,
    allow_missing_media_tools: bool = False,
) -> dict[str, Any]:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        discovered_ffmpeg, discovered_ffprobe = _discover_windows_media_tools(
            Path(os.environ["LOCALAPPDATA"])
            if os.name == "nt" and os.environ.get("LOCALAPPDATA")
            else None,
            Path(os.environ["PROGRAMFILES"])
            if os.name == "nt" and os.environ.get("PROGRAMFILES")
            else None,
        )
        ffmpeg = ffmpeg or discovered_ffmpeg
        ffprobe = ffprobe or discovered_ffprobe
    faster_whisper = importlib.util.find_spec("faster_whisper") is not None
    try:
        from local_meeting_ai.config import AppSettings
        from local_meeting_ai.paths import AppPaths

        paths = AppPaths.from_settings(AppSettings())
        configured_models_dir = AppSettings().models_dir
        resolved_models_dir = (
            models_dir
            or configured_models_dir
            or _saved_models_directory(paths.database)
            or paths.models
        )
    except Exception:
        resolved_models_dir = models_dir

    whisper_model_ready = None
    if require_whisper_model:
        whisper_model_ready = bool(
            resolved_models_dir and _model_installed(resolved_models_dir, require_whisper_model)
        )

    checks = {
        "python": {
            "status": "ready" if sys.version_info >= (3, 11) else "missing",
            "version": sys.version.split()[0],
            "minimum": "3.11",
        },
        "media_tools": {
            "status": "ready"
            if ffmpeg and ffprobe
            else "optional-missing"
            if allow_missing_media_tools
            else "missing",
            "ffmpeg": ffmpeg,
            "ffprobe": ffprobe,
            "required_for": "media import, normalization, and transcription",
        },
        "transcription_runtime": {
            "status": "ready" if faster_whisper else "missing",
            "package": "faster-whisper",
        },
        "transcription_model": {
            "status": (
                "not-checked"
                if require_whisper_model is None
                else "ready"
                if whisper_model_ready
                else "missing"
            ),
            "model": require_whisper_model,
            "directory": str(resolved_models_dir) if resolved_models_dir else None,
        },
        "diarization_runtime": {
            "status": "ready" if importlib.util.find_spec("sherpa_onnx") else "optional-missing",
            "package": "sherpa-onnx",
            "optional": True,
        },
        "local_summary_runtime": {
            "status": "ready" if importlib.util.find_spec("llama_cpp") else "optional-missing",
            "package": "llama-cpp-python",
            "optional": True,
            "note": "A compatible runtime wheel may not exist for this Python and Windows setup.",
        },
    }
    required_checks = ("python", "media_tools", "transcription_runtime")
    if require_whisper_model:
        required_checks += ("transcription_model",)
    errors = [
        name
        for name in required_checks
        if checks[name]["status"] != "ready"
        and not (name == "media_tools" and allow_missing_media_tools)
    ]
    ready = not errors and checks["media_tools"]["status"] == "ready"
    return {
        "ready": ready,
        "errors": errors,
        "platform": platform.platform(),
        "models_directory": str(resolved_models_dir) if resolved_models_dir else None,
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Meet2Notes installation readiness.")
    parser.add_argument("--models-dir", type=Path, help="Model directory override.")
    parser.add_argument(
        "--require-whisper-model",
        choices=("tiny", "base", "small", "medium", "large-v3", "distil-large-v3", "turbo"),
        help="Fail the readiness check unless this local model is installed.",
    )
    parser.add_argument(
        "--allow-missing-media-tools",
        action="store_true",
        help="Report missing FFmpeg/FFprobe as optional (for offline/development setup).",
    )
    arguments = parser.parse_args()
    report = collect_environment_report(
        models_dir=arguments.models_dir,
        require_whisper_model=arguments.require_whisper_model,
        allow_missing_media_tools=arguments.allow_missing_media_tools,
    )
    print(json.dumps(report, indent=2))
    if report["ready"]:
        print("Meet2Notes readiness: READY")
        return 0
    print("Meet2Notes readiness: INCOMPLETE", file=sys.stderr)
    for name in report["errors"]:
        print(f"  Missing required setup: {name}", file=sys.stderr)
    return 0 if arguments.allow_missing_media_tools else 1


if __name__ == "__main__":
    raise SystemExit(main())
