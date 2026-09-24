"""Compare two local transcripts without exporting meeting text."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import statistics
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path


def tokens(text: str) -> list[str]:
    folded = unicodedata.normalize("NFKD", text.casefold())
    return re.findall(r"\w+", "".join(c for c in folded if not unicodedata.combining(c)))


def transcript_windows(
    db: sqlite3.Connection, transcription_id: int
) -> tuple[int, list[str], dict[int, list[str]]]:
    rows = db.execute(
        "SELECT start_ms, text FROM transcript_segments "
        "WHERE transcription_id = ? ORDER BY segment_index",
        (transcription_id,),
    ).fetchall()
    windows: dict[int, list[str]] = {}
    all_tokens: list[str] = []
    for start_ms, text in rows:
        words = tokens(text)
        windows.setdefault(start_ms // 60_000, []).extend(words)
        all_tokens.extend(words)
    return len(rows), all_tokens, windows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    parser.add_argument("first_id", type=int)
    parser.add_argument("second_id", type=int)
    args = parser.parse_args()
    db = sqlite3.connect(f"file:{args.database.as_posix()}?mode=ro", uri=True)
    try:
        first_count, first_words, first_windows = transcript_windows(db, args.first_id)
        second_count, second_words, second_windows = transcript_windows(db, args.second_id)
    finally:
        db.close()
    keys = sorted(set(first_windows) | set(second_windows))
    similarity = [
        SequenceMatcher(
            None, first_windows.get(key, []), second_windows.get(key, []), autojunk=False
        ).ratio()
        for key in keys
        if first_windows.get(key) or second_windows.get(key)
    ]
    result = {
        "first": {"id": args.first_id, "segments": first_count, "words": len(first_words)},
        "second": {"id": args.second_id, "segments": second_count, "words": len(second_words)},
        "minute_windows": len(similarity),
        "mean_token_agreement": round(statistics.mean(similarity), 3) if similarity else None,
        "median_token_agreement": round(statistics.median(similarity), 3) if similarity else None,
        "minimum_token_agreement": round(min(similarity), 3) if similarity else None,
        "note": "Agreement between two machine transcripts; not accuracy against human reference.",
    }
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
