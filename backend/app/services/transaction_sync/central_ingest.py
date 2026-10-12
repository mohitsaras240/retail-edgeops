"""Central event ingestion endpoint.
Receives transaction batches from stores and stores them centrally with idempotent deduplication.
"""
from __future__ import annotations

import os
import sqlite3
import threading
import time
from typing import Any
from fastapi import APIRouter
from pydantic import BaseModel, Field


class IngestEventItem(BaseModel):
    event_id: str
    store_id: str
    terminal_id: str
    item_count: int
    created_at: float
    canary: bool = False


class IngestBatchRequest(BaseModel):
    store_id: str
    events: list[IngestEventItem]


class CentralIngestService:
    def __init__(self, db_path: str = "data/central-events.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS central_transactions ("
                    " event_id TEXT PRIMARY KEY,"
                    " store_id TEXT NOT NULL,"
                    " terminal_id TEXT NOT NULL,"
                    " item_count INTEGER NOT NULL,"
                    " created_at REAL NOT NULL,"
                    " ingested_at REAL NOT NULL,"
                    " canary INTEGER NOT NULL DEFAULT 0)"
                )
                conn.commit()
            finally:
                conn.close()

    def ingest_batch(self, store_id: str, events: list[IngestEventItem]) -> dict[str, Any]:
        accepted = 0
        duplicates = 0
        now = time.time()
        with self._lock:
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                for ev in events:
                    cur.execute(
                        "INSERT OR IGNORE INTO central_transactions "
                        "(event_id, store_id, terminal_id, item_count, created_at, ingested_at, canary) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (ev.event_id, ev.store_id, ev.terminal_id, ev.item_count, ev.created_at, now, int(ev.canary)),
                    )
                    if cur.rowcount > 0:
                        accepted += 1
                    else:
                        duplicates += 1
                conn.commit()
            finally:
                conn.close()

        return {
            "status": "ok",
            "store_id": store_id,
            "received": len(events),
            "accepted": accepted,
            "duplicates": duplicates,
        }

    def stats(self) -> dict[str, Any]:
        with self._lock:
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                total = cur.execute("SELECT COUNT(*) FROM central_transactions").fetchone()[0]
                stores = cur.execute("SELECT COUNT(DISTINCT store_id) FROM central_transactions").fetchone()[0]
                return {"total_transactions": total, "distinct_stores": stores}
            finally:
                conn.close()


def create_central_ingest_router(service: CentralIngestService) -> APIRouter:
    router = APIRouter(prefix="/central", tags=["central_ingest"])

    @router.post("/ingest")
    def ingest_events(req: IngestBatchRequest) -> dict:
        return service.ingest_batch(req.store_id, req.events)

    @router.get("/stats")
    def ingest_stats() -> dict:
        return service.stats()

    return router
