from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Optional


class AuditLog:
    """Append-only audit trail (memory + optional JSON-lines file)."""

    def __init__(self, path: Optional[Path] = None):
        self._path = Path(path) if path else None
        self._lock = threading.Lock()
        self._entries: list[dict[str, Any]] = []

    def append(self, event: str, data: dict[str, Any], ts: Optional[float] = None) -> None:
        entry = {"ts": time.time() if ts is None else ts, "event": event, **data}
        with self._lock:
            self._entries.append(entry)
            if self._path:
                with self._path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(entry, default=str) + "\n")

    def entries(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._entries)
