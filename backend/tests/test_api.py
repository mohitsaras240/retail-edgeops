import importlib.util
import tempfile
import unittest
from pathlib import Path

HAVE = importlib.util.find_spec("fastapi") is not None and importlib.util.find_spec("httpx") is not None


@unittest.skipUnless(HAVE, "fastapi/httpx not installed: API tests skipped")
class ApiTests(unittest.TestCase):
    KEY = "k" * 20

    def setUp(self):
        from fastapi.testclient import TestClient
        from app.api.routes import create_app
        from app.services.transaction_sync.central_ingest import CentralIngestService
        from tests.helpers import make_three_store_engine

        self.tmp = tempfile.TemporaryDirectory()
        self.central_db = str(Path(self.tmp.name) / "central_test.db")
        self.central_service = CentralIngestService(self.central_db)

        self.eng, self.sim, self.clock = make_three_store_engine()
        self.client = TestClient(
            create_app(self.eng, api_key=self.KEY, run_loop=False, central_service=self.central_service)
        )
        self.h = {"X-API-Key": self.KEY}

    def tearDown(self):
        self.tmp.cleanup()

    def test_health_is_public_and_labels_provenance(self):
        r = self.client.get("/api/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["provenance"], "simulated")

    def test_management_endpoints_require_key(self):
        for path in ("/api/workloads", "/api/incidents", "/api/audit", "/api/stores", "/api/sync/status"):
            self.assertEqual(self.client.get(path).status_code, 401)
            self.assertEqual(self.client.get(path, headers={"X-API-Key": "wrong"}).status_code, 401)
        self.assertEqual(self.client.post("/api/incidents/x/approve", json={"actor": "a"}).status_code, 401)

    def test_weak_key_refuses_to_start(self):
        from app.api.routes import create_app

        with self.assertRaises(RuntimeError):
            create_app(self.eng, api_key="short", run_loop=False)

    def test_approval_flow_over_http(self):
        from tests.helpers import run

        self.sim.degrade("rea-store001-pos")
        run(self.eng, self.clock, 5)
        inc = self.client.get("/api/incidents", headers=self.h).json()[0]
        self.assertEqual(inc["state"], "AWAITING_APPROVAL")
        bad = self.client.post(f"/api/incidents/{inc['id']}/approve", headers=self.h, json={"actor": "a;rm -rf"})
        self.assertEqual(bad.status_code, 422)
        ok = self.client.post(f"/api/incidents/{inc['id']}/approve", headers=self.h, json={"actor": "alice"})
        self.assertEqual(ok.status_code, 200)
        again = self.client.post(f"/api/incidents/{inc['id']}/approve", headers=self.h, json={"actor": "alice"})
        self.assertEqual(again.status_code, 409)
        self.assertEqual(self.client.get("/api/incidents/nope", headers=self.h).status_code, 404)

    def test_stores_endpoints(self):
        stores_resp = self.client.get("/api/stores", headers=self.h)
        self.assertEqual(stores_resp.status_code, 200)
        stores = stores_resp.json()
        self.assertEqual(len(stores), 3)

        # Per-store detail
        detail_resp = self.client.get("/api/stores/store-001", headers=self.h)
        self.assertEqual(detail_resp.status_code, 200)
        detail = detail_resp.json()
        self.assertEqual(detail["store_id"], "store-001")
        self.assertEqual(len(detail["workloads"]), 3)

        # 404 on nonexistent store
        self.assertEqual(self.client.get("/api/stores/store-999", headers=self.h).status_code, 404)

    def test_sync_status_endpoint_and_central_ingest(self):
        # 1. Check sync aggregate status
        sync_resp = self.client.get("/api/sync/status", headers=self.h)
        self.assertEqual(sync_resp.status_code, 200)
        data = sync_resp.json()
        self.assertIn("stores", data)
        self.assertIn("central_stats", data)

        # 2. Ingest transaction via mounted /central/ingest router
        payload = {
            "store_id": "store-001",
            "events": [
                {
                    "event_id": "api-ev-1",
                    "store_id": "store-001",
                    "terminal_id": "T1",
                    "item_count": 2,
                    "created_at": 1000.0,
                    "canary": False,
                }
            ],
        }
        ingest_resp = self.client.post("/central/ingest", json=payload)
        self.assertEqual(ingest_resp.status_code, 200)
        res = ingest_resp.json()
        self.assertEqual(res["accepted"], 1)
        self.assertEqual(res["duplicates"], 0)


if __name__ == "__main__":
    unittest.main()
