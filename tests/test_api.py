import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from telemetry_lab.api import create_app


class ApiIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(create_app())

    def test_health_and_presets_are_available(self):
        health = self.client.get("/health")
        presets = self.client.get("/api/v1/presets")

        self.assertEqual(200, health.status_code)
        self.assertEqual("ok", health.json()["data"]["status"])
        self.assertGreaterEqual(len(presets.json()["data"]), 3)
        self.assertEqual("nosniff", health.headers["x-content-type-options"])

    def test_create_scenario_returns_enveloped_metrics(self):
        response = self.client.post(
            "/api/v1/scenarios",
            json={"name": "API run", "seed": 27, "charger_count": 2, "samples_per_charger": 10, "preset": "mixed-faults"},
        )

        self.assertEqual(201, response.status_code)
        payload = response.json()
        self.assertTrue(payload["success"])
        self.assertEqual(20, payload["data"]["metrics"]["total_input"])
        self.assertIn("recovery_actions", payload["data"])

    def test_create_scenario_rejects_unbounded_workload(self):
        response = self.client.post(
            "/api/v1/scenarios",
            json={"name": "too large", "charger_count": 999, "samples_per_charger": 10},
        )

        self.assertEqual(422, response.status_code)
        self.assertEqual(
            {"success": False, "data": None, "error": "validation failed"},
            response.json(),
        )

    def test_request_body_limit_is_enforced_before_parsing(self):
        response = self.client.post(
            "/api/v1/scenarios",
            content=b"{}",
            headers={"content-type": "application/json", "content-length": "999999"},
        )

        self.assertEqual(413, response.status_code)
        self.assertFalse(response.json()["success"])

    def test_per_client_rate_limit_covers_health_endpoint(self):
        responses = [self.client.get("/health") for _ in range(101)]

        self.assertEqual(200, responses[99].status_code)
        self.assertEqual(429, responses[100].status_code)
        self.assertEqual("60", responses[100].headers["retry-after"])

    def test_scenario_endpoint_has_a_stricter_per_client_limit(self):
        payload = {
            "name": "rate limit",
            "preset": "baseline",
            "charger_count": 1,
            "samples_per_charger": 5,
        }
        responses = [self.client.post("/api/v1/scenarios", json=payload) for _ in range(13)]

        self.assertEqual(201, responses[11].status_code)
        self.assertEqual(429, responses[12].status_code)

    def test_api_reference_is_local_and_compatible_with_csp(self):
        response = self.client.get("/api/docs")

        self.assertEqual(200, response.status_code)
        self.assertNotIn("jsdelivr", response.text)
        self.assertNotIn("https://", response.text)
        self.assertIn("default-src 'self'", response.headers["content-security-policy"])

    def test_large_run_returns_bounded_collections_with_complete_totals(self):
        response = self.client.post(
            "/api/v1/scenarios",
            json={
                "name": "bounded response",
                "preset": "mixed-faults",
                "seed": 27,
                "charger_count": 5,
                "samples_per_charger": 200,
            },
        )

        data = response.json()["data"]
        self.assertEqual(1_000, data["meta"]["total_source_samples"])
        self.assertLessEqual(len(data["samples"]), 500)
        self.assertLess(len(response.content), 1_000_000)

    def test_unexpected_errors_are_generic_and_keep_security_headers(self):
        with patch("telemetry_lab.api.run_scenario", side_effect=RuntimeError("secret detail")):
            response = self.client.post(
                "/api/v1/scenarios",
                json={"name": "failure", "preset": "baseline", "charger_count": 1, "samples_per_charger": 5},
            )

        self.assertEqual(500, response.status_code)
        self.assertEqual("internal server error", response.json()["error"])
        self.assertNotIn("secret detail", response.text)
        self.assertEqual("nosniff", response.headers["x-content-type-options"])
        self.assertIn("default-src 'self'", response.headers["content-security-policy"])


if __name__ == "__main__":
    unittest.main()
