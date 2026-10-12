import importlib.util
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from app.services.telemetry.prober import HttpProber
from tests.helpers import spec

SIM_PATH = Path(__file__).resolve().parents[2] / "workloads" / "pos_simulator" / "app.py"
_spec = importlib.util.spec_from_file_location("pos_sim", SIM_PATH)
pos = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pos)


class Server:
    def __init__(self, db, faults=True):
        self.state = pos.PosState(db, "store-t", enable_fault_endpoints=faults)
        self.srv = pos.make_server(self.state)
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def stop(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.state.close()

    def call(self, path, method="GET", body=None):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=3) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())


class PosSimulatorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / "pos.db")
        self.s = Server(self.db)

    def tearDown(self):
        self.s.stop()
        self.tmp.cleanup()

    def test_health_and_transaction(self):
        self.assertEqual(self.s.call("/health")[0], 200)
        code, body = self.s.call("/transaction", "POST", {"terminal_id": "T1", "item_count": 3})
        self.assertEqual(code, 201)
        self.assertEqual(len(body["event_id"]), 32)
        self.assertEqual(self.s.call("/stats")[1]["transactions_total"], 1)

    def test_event_ids_are_unique(self):
        ids = {self.s.call("/transaction", "POST", {"item_count": 1})[1]["event_id"] for _ in range(25)}
        self.assertEqual(len(ids), 25)

    def test_input_validation(self):
        for bad in ({"item_count": 0}, {"item_count": 999}, {"item_count": "3"}, {"terminal_id": "a b;"},
                    {"item_count": True}, {"canary": "yes"}):
            self.assertEqual(self.s.call("/transaction", "POST", bad)[0], 400, bad)

    def test_transactions_survive_service_restart(self):
        for _ in range(5):
            self.s.call("/transaction", "POST", {"item_count": 2})
        self.s.stop()
        self.s = Server(self.db)
        self.assertEqual(self.s.call("/stats")[1]["transactions_total"], 5)

    def test_degrade_fault_then_restart_clears_it(self):
        self.s.call("/_fault/degrade", "POST", {})
        self.assertEqual(self.s.call("/health")[0], 503)
        self.assertEqual(self.s.call("/transaction", "POST", {"item_count": 1})[0], 503)
        self.s.stop()
        self.s = Server(self.db)                               # "restart": fault flag is in memory
        self.assertEqual(self.s.call("/health")[0], 200)

    def test_fault_endpoints_disabled_by_default(self):
        self.s.stop()
        self.s = Server(self.db, faults=False)
        self.assertEqual(self.s.call("/_fault/degrade", "POST", {})[0], 404)

    def test_canary_excluded_from_business_counts(self):
        prober = HttpProber(timeout_s=2)
        sp = spec("x", "s")
        sp = type(sp)(**{**sp.__dict__, "health_url": self.s.base + "/health",
                         "transaction_url": self.s.base + "/transaction"})
        self.assertTrue(prober.probe_health(sp).ok)
        self.assertTrue(prober.probe_canary(sp).ok)
        stats = self.s.call("/stats")[1]
        self.assertEqual((stats["transactions_total"], stats["canary_total"]), (0, 1))

    def test_prober_reports_failure_when_service_is_down(self):
        sp = spec("x", "s")
        base = self.s.base
        self.s.stop()
        sp = type(sp)(**{**sp.__dict__, "health_url": base + "/health"})
        res = HttpProber(timeout_s=1).probe_health(sp)
        self.assertFalse(res.ok)
        self.assertIsNotNone(res.error)
        self.s = Server(self.db)                               # so tearDown has something to stop

    def test_prober_reports_503_as_failure_with_code(self):
        self.s.call("/_fault/degrade", "POST", {})
        sp = spec("x", "s")
        sp = type(sp)(**{**sp.__dict__, "health_url": self.s.base + "/health"})
        res = HttpProber(timeout_s=1).probe_health(sp)
        self.assertEqual((res.ok, res.status_code), (False, 503))


if __name__ == "__main__":
    unittest.main()
