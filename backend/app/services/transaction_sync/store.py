"""Offline transaction persistence in SQLite.
Thread-safe, idempotent, survives process restarts.
Tracks local transaction lifecycle: PENDING_SYNC -> SYNCED / FAILED.
"""
from __future__ import annotations

import os
import sqlite3
import threading
import time
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class TransactionEvent:
    event_id: str
    store_id: str
    terminal_id: str
    item_count: int
    created_at: float
    status: str = "PENDING_SYNC"
    synced_at: Optional[float] = None
    fail_reason: Optional[str] = None
    canary: bool = False


class TransactionStore:
    def __init__(self, db_path: str):
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
                    "CREATE TABLE IF NOT EXISTS transactions ("
                    " event_id TEXT PRIMARY KEY,"
                    " store_id TEXT NOT NULL,"
                    " terminal_id TEXT NOT NULL,"
                    " item_count INTEGER NOT NULL,"
                    " created_at REAL NOT NULL,"
                    " status TEXT NOT NULL,"
                    " synced_at REAL,"
                    " fail_reason TEXT,"
                    " canary INTEGER NOT NULL DEFAULT 0)"
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_status ON transactions(status)")
                conn.commit()
            finally:
                conn.close()

    def enqueue(self, event: TransactionEvent) -> bool:
        """Enqueue transaction event. Idempotent: returns False if event_id already exists."""
        with self._lock:
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                cur.execute(
                    "INSERT OR IGNORE INTO transactions "
                    "(event_id, store_id, terminal_id, item_count, created_at, status, synced_at, fail_reason, canary) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        event.event_id,
                        event.store_id,
                        event.terminal_id,
                        event.item_count,
                        event.created_at,
                        event.status,
                        event.synced_at,
                        event.fail_reason,
                        int(event.canary),
                    ),
                )
                conn.commit()
                return cur.rowcount > 0
            finally:
                conn.close()

    def get_pending(self, limit: int = 50) -> list[TransactionEvent]:
        with self._lock:
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                rows = cur.execute(
                    "SELECT event_id, store_id, terminal_id, item_count, created_at, status, synced_at, fail_reason, canary "
                    "FROM transactions WHERE status='PENDING_SYNC' ORDER BY created_at ASC LIMIT ?",
                    (limit,),
                ).fetchall()
                return [
                    TransactionEvent(
                        event_id=r[0],
                        store_id=r[1],
                        terminal_id=r[2],
                        item_count=r[3],
                        created_at=r[4],
                        status=r[5],
                        synced_at=r[6],
                        fail_reason=r[7],
                        canary=bool(r[8]),
                    )
                    for r in rows
                ]
            finally:
                conn.close()

    def mark_synced(self, event_ids: list[str], synced_at: Optional[float] = None) -> int:
        if not event_ids:
            return 0
        ts = synced_at or time.time()
        with self._lock:
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                cur.executemany(
                    "UPDATE transactions SET status='SYNCED', synced_at=? WHERE event_id=?",
                    [(ts, eid) for eid in event_ids],
                )
                conn.commit()
                return cur.rowcount
            finally:
                conn.close()

    def mark_failed(self, event_ids: list[str], reason: str) -> int:
        if not event_ids:
            return 0
        with self._lock:
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                cur.executemany(
                    "UPDATE transactions SET status='FAILED', fail_reason=? WHERE event_id=?",
                    [(reason, eid) for eid in event_ids],
                )
                conn.commit()
                return cur.rowcount
            finally:
                conn.close()

    def status(self) -> dict:
        with self._lock:
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                pending = cur.execute("SELECT COUNT(*) FROM transactions WHERE status='PENDING_SYNC'").fetchone()[0]
                synced = cur.execute("SELECT COUNT(*) FROM transactions WHERE status='SYNCED'").fetchone()[0]
                failed = cur.execute("SELECT COUNT(*) FROM transactions WHERE status='FAILED'").fetchone()[0]
                total = cur.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
                return {
                    "pending_count": pending,
                    "synced_count": synced,
                    "failed_count": failed,
                    "total_count": total,
                }
            finally:
                conn.close()
