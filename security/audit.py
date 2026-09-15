"""Append-only, minimum-necessary audit log (HIPAA Security Rule alignment)."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from security.phi import redact_phi

LOG_DIR = Path("logs")
LOG_FILE = LOG_DIR / "audit.jsonl"


def _preview(text: str, limit: int = 120) -> str:
    redacted, _ = redact_phi(text)
    return redacted[:limit]


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def log_event(
    event_type: str,
    question: str = "",
    indexed_file: str = "",
    reason: str = "",
    extra: dict | None = None,
) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    safe_extra = dict(extra or {})
    for key in ("question", "answer", "raw_text", "ssn", "name", "address"):
        safe_extra.pop(key, None)

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event_type,
        "indexed_file": indexed_file,
        "question_preview": _preview(question),
        "question_hash": _hash(question) if question else "",
        "reason": reason,
        "extra": safe_extra,
    }

    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
