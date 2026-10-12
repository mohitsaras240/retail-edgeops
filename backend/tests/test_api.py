import importlib.util
import unittest

HAVE = importlib.util.find_spec("fastapi") is not None and importlib.util.find_spec("httpx") is not None


@unittest.skipUnless(HAVE, "fastapi/httpx not installed: API tests skipped")
class ApiTests(unittest.TestCase):
    KEY = "k" * 20

    def setUp(self):
        from fastapi.testclient import TestClient
        from app.api.routes import create_app
        from tests.helpers import make_engine
        self.eng, self.sim, self.clock = make_engine()
        self.client = TestClient(create_app(self.eng, api_key=self.KEY, run_loop=False))
        self.h = {"X-API-Key": self.KEY}

    def test_health_is_public_and_labels_provenance(self):
        r = self.client.get("/api/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["provenance"], "simulated")

    def test_management_endpoints_require_key(self):
        for path in ("/api/workloads", "/api/incidents", "/api/audit"):
            self.assertEqual(self.client.get(path).status_code, 401)
            self.assertEqual(self.client.get(path, headers={"X-API-Key": "wrong"}).status_code, 401)
        self.assertEqual(self.client.post("/api/incidents/x/approve", json={"actor": "a"}).status_code, 401)

    def test_weak_key_refuses_to_start(self):
        from app.api.routes import create_app
        with self.assertRaises(RuntimeError):
            create_app(self.eng, api_key="short", run_loop=False)

    def test_approval_flow_over_http(self):
        from tests.helpers import run
        self.sim.degrade("pos-a")
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


if __name__ == "__main__":
    unittest.main()
