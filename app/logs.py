"""Structured logging: one JSON object per line in <ACME_LOG_DIR>/<stream>.jsonl."""
import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from app import config

_lock = threading.Lock()


def now() -> str:
    """UTC ISO-8601 with seconds, e.g. 2026-11-04T18:22:05+00:00."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def write(stream: str, **fields) -> dict:
    record = {"ts": now(), **fields}
    directory = Path(config.log_dir())
    directory.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False)
    with _lock:
        with open(directory / f"{stream}.jsonl", "a", encoding="utf-8", newline="\n") as f:
            f.write(line + "\n")
    return record
