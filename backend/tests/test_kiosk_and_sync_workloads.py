import importlib.util
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

KIOSK_PATH = Path(__file__).resolve().parents[2] / "workloads" / "kiosk_simulator" / "app.py"
_k_spec = importlib.util.spec_from_file_location("kiosk_sim", KIOSK_PATH)
kiosk_mod = importlib.util.module_from_spec(_k_spec)
_k_spec.loader.exec_module(kiosk_mod)

SYNC_PATH = Path(__file__).resolve().parents[2] / "workloads" / "transaction_sync" / "app.py"
_s_spec = importlib.util.spec_from_file_location("sync_sim", SYNC_PATH)
sync_mod = importlib.util.module_from_spec(_s_spec)
_s_spec.loader.exec_module(sync_mod)


class KioskWorkloadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / "kiosk.db")
        self.state = kiosk_mod.KioskState(self.db, "store-001", "kiosk-001", enable_fault_endpoints=True)
        self.srv = kiosk_mod.make_server(self.state)
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.state.close()
        self.tmp.cleanup()

    def _call(self, path, method="GET", body=None):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.base + path, data=data, method=method, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=3) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_kiosk_health_and_transaction(self):
        status, data = self._call("/health")
        self.assertEqual(status, 200)
        self.assertEqual(data["kiosk_id"], "kiosk-001")

        status, tx = self._call("/transaction", "POST", {"terminal_id": "kiosk-001", "item_count": 3})
        self.assertEqual(status, 201)
        self.assertEqual(tx["status"], "PENDING_SYNC")
        self.assertIn("event_id", tx)

    def test_kiosk_degrade_and_recovery(self):
        self._call("/_fault/degrade", "POST", {})
        self.assertEqual(self._call("/health")[0], 503)
        self.assertEqual(self._call("/transaction", "POST", {"item_count": 1})[0], 503)

        self._call("/_fault/clear", "POST", {})
        self.assertEqual(self._call("/health")[0], 200)


class SyncWorkloadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / "sync_workload.db")
        # Initialize state with a dummy central url and stopped worker loop
        self.state = sync_mod.SyncWorkerState(
            self.db, "store-001", "http://127.0.0.1:9999/central/ingest", interval_s=60.0, enable_fault_endpoints=True
        )
        self.srv = sync_mod.make_server(self.state)
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.state.close()
        self.tmp.cleanup()

    def _call(self, path, method="GET", body=None):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.base + path, data=data, method=method, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=3) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_sync_workload_status_and_health(self):
        status, data = self._call("/health")
        self.assertEqual(status, 200)
        self.assertEqual(data["pending_count"], 0)

        status, st = self._call("/sync/status")
        self.assertEqual(status, 200)
        self.assertFalse(st["blocked"])

    def test_sync_workload_block_fault(self):
        self._call("/_fault/block", "POST", {})
        status, data = self._call("/health")
        self.assertEqual(status, 503)
        self.assertTrue(data["blocked"])

        self._call("/_fault/unblock", "POST", {})
        status, data = self._call("/health")
        self.assertEqual(status, 200)
        self.assertFalse(data["blocked"])


if __name__ == "__main__":
    unittest.main()
