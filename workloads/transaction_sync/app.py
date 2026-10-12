"""Transaction sync service workload.
Monitors local store transactions in SQLite and pushes pending events to central ingest.
Supports offline resilience: buffers during disconnect, syncs upon reconnect.
Endpoints:
  GET /health
  GET /stats
  GET /sync/status
  POST /sync/trigger
  POST /_fault/block /_fault/unblock (demo only when ENABLE_FAULT_ENDPOINTS=1)
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class SyncWorkerState:
    def __init__(
        self,
        db_path: str,
        store_id: str,
        central_url: str,
        interval_s: float = 5.0,
        enable_fault_endpoints: bool = False,
    ):
        self.db_path = db_path
        self.store_id = store_id
        self.central_url = central_url
        self.interval_s = interval_s
        self.enable_fault_endpoints = enable_fault_endpoints

        self.started = time.time()
        self.blocked = False
        self.synced_total = 0
        self.failed_total = 0
        self.last_sync_ts = 0.0
        self.last_sync_error: str | None = None

        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._worker_thread = threading.Thread(target=self._run_loop, daemon=True)
        self._worker_thread.start()

    def _get_db(self):
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS transactions ("
            " event_id TEXT PRIMARY KEY, created_at REAL NOT NULL,"
            " store_id TEXT NOT NULL, terminal_id TEXT NOT NULL, item_count INTEGER NOT NULL,"
            " status TEXT NOT NULL, canary INTEGER NOT NULL DEFAULT 0)"
        )
        return conn

    def status(self) -> dict:
        with self._lock:
            conn = self._get_db()
            try:
                cur = conn.cursor()
                pending = cur.execute("SELECT COUNT(*) FROM transactions WHERE status='PENDING_SYNC'").fetchone()[0]
                synced = cur.execute("SELECT COUNT(*) FROM transactions WHERE status='SYNCED'").fetchone()[0]
            finally:
                conn.close()

            return {
                "store_id": self.store_id,
                "pending_count": pending,
                "synced_count": synced,
                "synced_total": self.synced_total,
                "failed_total": self.failed_total,
                "blocked": self.blocked,
                "last_sync_ts": self.last_sync_ts,
                "last_sync_error": self.last_sync_error,
                "uptime_s": round(time.time() - self.started, 1),
            }

    def health(self) -> tuple[int, dict]:
        st = self.status()
        if self.blocked:
            return 503, {"status": "degraded", "reason": "sync_blocked", **st}
        return 200, {"status": "ok", **st}

    def sync_once(self) -> dict:
        if self.blocked:
            self.last_sync_error = "sync is blocked by fault injection"
            return {"status": "blocked", "synced": 0}

        conn = self._get_db()
        try:
            cur = conn.cursor()
            rows = cur.execute(
                "SELECT event_id, created_at, store_id, terminal_id, item_count, canary "
                "FROM transactions WHERE status='PENDING_SYNC' LIMIT 50"
            ).fetchall()

            if not rows:
                return {"status": "idle", "synced": 0}

            events = [
                {
                    "event_id": r[0],
                    "created_at": r[1],
                    "store_id": r[2],
                    "terminal_id": r[3],
                    "item_count": r[4],
                    "canary": bool(r[5]),
                }
                for r in rows
            ]

            payload = json.dumps({"store_id": self.store_id, "events": events}).encode("utf-8")
            req = urllib.request.Request(
                self.central_url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            try:
                with urllib.request.urlopen(req, timeout=5) as resp:
                    if resp.status in (200, 201):
                        event_ids = [e["event_id"] for e in events]
                        cur.executemany(
                            "UPDATE transactions SET status='SYNCED' WHERE event_id=?",
                            [(eid,) for eid in event_ids],
                        )
                        conn.commit()
                        with self._lock:
                            self.synced_total += len(event_ids)
                            self.last_sync_ts = time.time()
                            self.last_sync_error = None
                        return {"status": "ok", "synced": len(event_ids)}
                    else:
                        raise RuntimeError(f"Unexpected status: {resp.status}")
            except Exception as e:
                with self._lock:
                    self.failed_total += 1
                    self.last_sync_error = str(e)
                return {"status": "error", "error": str(e), "synced": 0}
        finally:
            conn.close()

    def _run_loop(self):
        while not self._stop_event.is_set():
            try:
                self.sync_once()
            except Exception as ex:
                with self._lock:
                    self.last_sync_error = str(ex)
            self._stop_event.wait(self.interval_s)

    def close(self):
        self._stop_event.set()
        self._worker_thread.join(timeout=2)


def make_server(state: SyncWorkerState, host: str = "127.0.0.1", port: int = 0) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def _send(self, code: int, body: dict) -> None:
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _body(self) -> dict | None:
            try:
                n = int(self.headers.get("Content-Length", "0"))
                if n > 4096:
                    return None
                return json.loads(self.rfile.read(n) or b"{}")
            except (ValueError, TypeError):
                return None

        def do_GET(self):
            if self.path == "/health":
                self._send(*state.health())
            elif self.path in ("/stats", "/sync/status"):
                self._send(200, state.status())
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self):
            if self.path == "/sync/trigger":
                self._body()
                res = state.sync_once()
                self._send(200, res)
            elif self.path in ("/_fault/block", "/_fault/unblock") and state.enable_fault_endpoints:
                self._body()
                state.blocked = (self.path == "/_fault/block")
                self._send(200, {"blocked": state.blocked})
            else:
                self._body()
                self._send(404, {"error": "not found"})

    return ThreadingHTTPServer((host, port), Handler)


if __name__ == "__main__":
    st = SyncWorkerState(
        os.environ.get("DB_PATH", "/data/pos.db"),
        os.environ.get("STORE_ID", "store-001"),
        os.environ.get("CENTRAL_URL", "http://autopilot-backend:8000/central/ingest"),
        float(os.environ.get("SYNC_INTERVAL_S", "5")),
        os.environ.get("ENABLE_FAULT_ENDPOINTS") == "1",
    )
    srv = make_server(st, "0.0.0.0", int(os.environ.get("PORT", "8080")))
    print(f"Transaction sync worker for {st.store_id} listening", flush=True)
    try:
        srv.serve_forever()
    finally:
        st.close()
