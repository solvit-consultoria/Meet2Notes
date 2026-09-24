"""Measure a short local WAV with Faster Whisper; print metrics, never transcript text."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import subprocess
import threading
import time
import unicodedata
import wave
from difflib import SequenceMatcher
from pathlib import Path

from faster_whisper import WhisperModel

from local_meeting_ai.adapters.transcription.faster_whisper import (
    _register_cuda_wheel_dll_directories,
)


def gpu_sample() -> tuple[int | None, int | None]:
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu,memory.used",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=3,
            check=True,
        )
        values = result.stdout.splitlines()[0].split(",")
        return int(values[0].strip()), int(values[1].strip())
    except (FileNotFoundError, IndexError, ValueError, subprocess.SubprocessError):
        return None, None


def tokens(text: str) -> list[str]:
    folded = unicodedata.normalize("NFKD", text.casefold())
    return re.findall(r"\w+", "".join(c for c in folded if not unicodedata.combining(c)))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio", type=Path)
    parser.add_argument("--model", default="small")
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--compute-type", default="int8_float16")
    parser.add_argument("--beam-size", type=int, default=5)
    parser.add_argument("--word-timestamps", action="store_true")
    parser.add_argument("--allow-download", action="store_true")
    parser.add_argument("--reference-database", type=Path)
    parser.add_argument("--reference-id", type=int)
    parser.add_argument("--reference-start-seconds", type=float, default=0)
    args = parser.parse_args()
    if args.device == "cuda" and not _register_cuda_wheel_dll_directories():
        raise RuntimeError("CUDA cuBLAS/cuDNN libraries are unavailable")
    with wave.open(str(args.audio), "rb") as wav:
        duration_seconds = wav.getnframes() / wav.getframerate()

    stop = threading.Event()
    samples: list[tuple[int | None, int | None]] = []

    def sample_gpu() -> None:
        while not stop.is_set():
            samples.append(gpu_sample())
            stop.wait(0.5)

    sampler = threading.Thread(target=sample_gpu, daemon=True)
    sampler.start()
    started = time.monotonic()
    try:
        model = WhisperModel(
            args.model,
            device=args.device,
            compute_type=args.compute_type,
            download_root=str(args.model_dir),
            local_files_only=not args.allow_download,
        )
        loaded = time.monotonic()
        segments, info = model.transcribe(
            str(args.audio),
            language="pt",
            beam_size=args.beam_size,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
            word_timestamps=args.word_timestamps,
            condition_on_previous_text=True,
        )
        segment_count = 0
        word_count = 0
        recognized: list[str] = []
        for segment in segments:
            segment_count += 1
            word_count += len(segment.text.split())
            recognized.extend(tokens(segment.text))
        finished = time.monotonic()
    finally:
        stop.set()
        sampler.join(timeout=4)
    gpu_util = [value for value, _ in samples if value is not None]
    gpu_memory = [value for _, value in samples if value is not None]
    agreement = None
    if args.reference_database and args.reference_id is not None:
        db = sqlite3.connect(f"file:{args.reference_database.as_posix()}?mode=ro", uri=True)
        try:
            reference = " ".join(
                row[0]
                for row in db.execute(
                    "SELECT text FROM transcript_segments "
                    "WHERE transcription_id = ? AND start_ms >= ? AND start_ms < ? "
                    "ORDER BY segment_index",
                    (
                        args.reference_id,
                        int(args.reference_start_seconds * 1000),
                        int((args.reference_start_seconds + duration_seconds) * 1000),
                    ),
                )
            )
        finally:
            db.close()
        agreement = round(
            SequenceMatcher(None, tokens(reference), recognized, autojunk=False).ratio(), 3
        )
    print(
        json.dumps(
            {
                "model": args.model,
                "device": args.device,
                "compute_type": args.compute_type,
                "beam_size": args.beam_size,
                "word_timestamps": args.word_timestamps,
                "duration_seconds": round(duration_seconds, 2),
                "model_load_seconds": round(loaded - started, 2),
                "inference_seconds": round(finished - loaded, 2),
                "realtime_factor": round((finished - loaded) / duration_seconds, 3),
                "segment_count": segment_count,
                "word_count": word_count,
                "reference_token_agreement": agreement,
                "detected_language": info.language,
                "peak_gpu_util_percent": max(gpu_util) if gpu_util else None,
                "peak_gpu_memory_used_mb": max(gpu_memory) if gpu_memory else None,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
