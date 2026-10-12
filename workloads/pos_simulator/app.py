"""Simulated PoS transaction service (synthetic data only; no payment processing).

Endpoints: GET /health, GET /stats, POST /transaction.
Demo-only fault endpoints (POST /_fault/degrade|clear) exist only when
ENABLE_FAULT_ENDPOINTS=1. The degraded flag is in memory, so a restart clears it.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_TERMINAL_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


class PosState:
    def __init__(self, db_path: str, store_id: str, enable_fault_endpoints: bool = False):
        self.store_id = store_id
        self.enable_fault_endpoints = enable_fault_endpoints
        self.started = time.time()
        self.degraded = False
        self.rejected = 0
        self._lock = threading.Lock()
        self._db = sqlite3.connect(db_path, check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS transactions (event_id TEXT PRIMARY KEY, created_at REAL NOT NULL,"
            " store_id TEXT NOT NULL, terminal_id TEXT NOT NULL, item_count INTEGER NOT NULL,"
            " status TEXT NOT NULL, canary INTEGER NOT NULL DEFAULT 0)")
        self._db.commit()

    def health(self) -> tuple[int, dict]:
        if self.degraded:
            return 503, {"status": "degraded", "store_id": self.store_id}
        with self._lock:
            self._db.execute("SELECT 1").fetchone()
        return 200, {"status": "ok", "store_id": self.store_id, "uptime_s": round(time.time() - self.started, 1)}

    def add_transaction(self, terminal_id: str, item_count: int, canary: bool) -> tuple[int, dict]:
        if self.degraded:
            self.rejected += 1
            return 503, {"error": "service degraded"}
        event_id = uuid.uuid4().hex
        with self._lock:
            self._db.execute(
                "INSERT INTO transactions (event_id, created_at, store_id, terminal_id, item_count, status, canary)"
                " VALUES (?,?,?,?,?,?,?)",
                (event_id, time.time(), self.store_id, terminal_id, item_count, "PENDING_SYNC", int(canary)))
            self._db.commit()
        return 201, {"event_id": event_id, "status": "PENDING_SYNC"}

    def stats(self) -> dict:
        with self._lock:
            real = self._db.execute("SELECT COUNT(*) FROM transactions WHERE canary=0").fetchone()[0]
            canary = self._db.execute("SELECT COUNT(*) FROM transactions WHERE canary=1").fetchone()[0]
        return {"store_id": self.store_id, "transactions_total": real, "canary_total": canary,
                "rejected_since_start": self.rejected, "degraded": self.degraded}

    def close(self) -> None:
        self._db.close()


def make_server(state: PosState, host: str = "127.0.0.1", port: int = 0) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):   # keep logs quiet; no transaction details are logged
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
            elif self.path == "/stats":
                self._send(200, state.stats())
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self):
            if self.path == "/transaction":
                body = self._body()
                if not isinstance(body, dict):
                    return self._send(400, {"error": "invalid JSON body"})
                terminal, items = body.get("terminal_id", "T1"), body.get("item_count", 1)
                canary = body.get("canary", False)
                if (not isinstance(terminal, str) or not _TERMINAL_RE.match(terminal)
                        or not isinstance(items, int) or isinstance(items, bool) or not 1 <= items <= 200
                        or not isinstance(canary, bool)):
                    return self._send(400, {"error": "validation failed"})
                return self._send(*state.add_transaction(terminal, items, canary))
            if self.path in ("/_fault/degrade", "/_fault/clear") and state.enable_fault_endpoints:
                state.degraded = self.path.endswith("degrade")
                return self._send(200, {"degraded": state.degraded})
            self._send(404, {"error": "not found"})

    return ThreadingHTTPServer((host, port), Handler)


if __name__ == "__main__":
    st = PosState(os.environ.get("DB_PATH", "/data/pos.db"), os.environ.get("STORE_ID", "store-001"),
                  os.environ.get("ENABLE_FAULT_ENDPOINTS") == "1")
    srv = make_server(st, "0.0.0.0", int(os.environ.get("PORT", "8080")))
    print(f"PoS simulator for {st.store_id} listening", flush=True)
    srv.serve_forever()
