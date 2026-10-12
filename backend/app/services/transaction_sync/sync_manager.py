"""Client-side sync coordinator that pushes pending transactions from TransactionStore to central ingest.
Supports disconnection simulation, background batch pushing, and error handling.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Optional

from app.services.transaction_sync.store import TransactionStore

log = logging.getLogger("autopilot.sync_manager")


class SyncManager:
    def __init__(
        self,
        store: TransactionStore,
        central_url: str,
        store_id: str,
        batch_size: int = 50,
        sync_interval_s: float = 2.0,
        clock: Callable[[], float] = time.time,
    ):
        self.store = store
        self.central_url = central_url
        self.store_id = store_id
        self.batch_size = batch_size
        self.sync_interval_s = sync_interval_s
        self.clock = clock

        self.disconnected = False
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        self.synced_total = 0
        self.duplicates_total = 0
        self.failed_cycles = 0
        self.last_sync_ts = 0.0
        self.last_sync_error: Optional[str] = None
        self._lock = threading.Lock()

    def simulate_disconnect(self) -> None:
        with self._lock:
            self.disconnected = True

    def reconnect(self) -> None:
        with self._lock:
            self.disconnected = False

    def sync_once(self) -> dict[str, Any]:
        with self._lock:
            if self.disconnected:
                self.last_sync_error = "network disconnected (simulated)"
                return {"status": "disconnected", "synced": 0, "error": self.last_sync_error}

        pending = self.store.get_pending(limit=self.batch_size)
        if not pending:
            return {"status": "idle", "synced": 0}

        events_payload = [
            {
                "event_id": ev.event_id,
                "store_id": ev.store_id,
                "terminal_id": ev.terminal_id,
                "item_count": ev.item_count,
                "created_at": ev.created_at,
                "canary": ev.canary,
            }
            for ev in pending
        ]

        data = json.dumps({"store_id": self.store_id, "events": events_payload}).encode("utf-8")
        req = urllib.request.Request(
            self.central_url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status in (200, 201):
                    res = json.loads(resp.read().decode("utf-8"))
                    eids = [ev.event_id for ev in pending]
                    now = self.clock()
                    self.store.mark_synced(eids, synced_at=now)
                    with self._lock:
                        self.synced_total += res.get("accepted", len(eids))
                        self.duplicates_total += res.get("duplicates", 0)
                        self.last_sync_ts = now
                        self.last_sync_error = None
                    return {
                        "status": "ok",
                        "synced": len(eids),
                        "accepted": res.get("accepted", len(eids)),
                        "duplicates": res.get("duplicates", 0),
                    }
                else:
                    raise RuntimeError(f"HTTP status {resp.status}")
        except Exception as ex:
            now = self.clock()
            with self._lock:
                self.failed_cycles += 1
                self.last_sync_error = str(ex)
            return {"status": "error", "error": str(ex), "synced": 0}

    def start_background(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name=f"sync-{self.store_id}")
        self._thread.start()

    def stop_background(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.sync_once()
            except Exception:
                log.exception("Background sync error")
            self._stop_event.wait(self.sync_interval_s)

    def metrics(self) -> dict[str, Any]:
        with self._lock:
            st = self.store.status()
            return {
                "store_id": self.store_id,
                "disconnected": self.disconnected,
                "synced_total": self.synced_total,
                "duplicates_total": self.duplicates_total,
                "failed_cycles": self.failed_cycles,
                "last_sync_ts": self.last_sync_ts,
                "last_sync_error": self.last_sync_error,
                **st,
            }
