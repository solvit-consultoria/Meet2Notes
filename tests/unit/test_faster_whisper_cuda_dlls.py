from __future__ import annotations

import ctypes
from pathlib import Path
from typing import Any

from local_meeting_ai.adapters.transcription import faster_whisper


def test_registers_cuda_wheel_directories_and_checks_both_runtimes(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    site_packages = tmp_path / "Lib" / "site-packages"
    cublas_bin = site_packages / "nvidia" / "cublas" / "bin"
    cudnn_bin = site_packages / "nvidia" / "cudnn" / "bin"
    cublas_bin.mkdir(parents=True)
    cudnn_bin.mkdir(parents=True)
    registered: list[str] = []
    loaded: list[str] = []
    handles = [object(), object()]

    monkeypatch.setattr(faster_whisper.sys, "platform", "win32")
    monkeypatch.setattr(faster_whisper, "_CUDA_DLL_DIRECTORY_HANDLES", [])
    monkeypatch.setattr(
        ctypes,
        "WinDLL",
        lambda name: loaded.append(name),
        raising=False,
    )

    def add_directory(path: str) -> object:
        registered.append(path)
        return handles[len(registered) - 1]

    assert faster_whisper._register_cuda_wheel_dll_directories(
        [str(site_packages)], add_dll_directory=add_directory
    )

    assert set(registered) == {str(cublas_bin), str(cudnn_bin)}
    assert loaded == ["cublas64_12.dll", "cudnn64_9.dll"]
    assert handles == faster_whisper._CUDA_DLL_DIRECTORY_HANDLES


def test_cuda_runtime_check_fails_if_either_dll_is_unavailable(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    site_packages = tmp_path / "site-packages"
    (site_packages / "nvidia" / "cublas" / "bin").mkdir(parents=True)
    (site_packages / "nvidia" / "cudnn" / "bin").mkdir(parents=True)
    loaded: list[str] = []

    def load(name: str) -> None:
        loaded.append(name)
        if name == "cudnn64_9.dll":
            raise OSError("missing cuDNN")

    monkeypatch.setattr(faster_whisper.sys, "platform", "win32")
    monkeypatch.setattr(faster_whisper, "_CUDA_DLL_DIRECTORY_HANDLES", [])
    monkeypatch.setattr(ctypes, "WinDLL", load, raising=False)
    monkeypatch.setattr(
        faster_whisper.os,
        "add_dll_directory",
        lambda _path: object(),
        raising=False,
    )

    assert not faster_whisper._register_cuda_wheel_dll_directories(
        [str(site_packages)]
    )
    assert loaded == ["cublas64_12.dll", "cudnn64_9.dll"]


def test_non_windows_skips_windows_dll_lookup(monkeypatch: Any) -> None:
    monkeypatch.setattr(faster_whisper.sys, "platform", "linux")
    assert faster_whisper._register_cuda_wheel_dll_directories([])
