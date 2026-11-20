"""Availability diagnostics expose only reason codes, never configuration values."""
import asyncio
import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
import httpx

from ai_support import AISupport, UsageLimiter
from portal_institucional import create_app


KEY = "sk-test-012345678901234567890123456789"
MODEL = "private-model-fixture"


class QuietAutomation:
    async def periodic_loop(self):
        await asyncio.Event().wait()

    async def close(self):
        pass


class SupportStatusTests(unittest.TestCase):
    def support(self, api_key=KEY, model=MODEL, daily_limit=100, storage_error=False):
        limiter = UsageLimiter(daily_limit=daily_limit, counter_path=None)
        limiter._storage_error = storage_error

        def no_provider(request):
            self.fail("Availability checks must never contact the AI provider")

        return AISupport(api_key=api_key, model=model, limiter=limiter,
                         transport=httpx.MockTransport(no_provider))

    def assert_status(self, support, issue):
        expected = {"ai_available": issue is None, "configuration_issue": issue}
        status = support.status()
        self.assertEqual(status, expected)
        self.assertEqual(support.config(), {"ai_available": issue is None})
        self.assertNotIn(KEY, json.dumps(status))
        self.assertNotIn(MODEL, json.dumps(status))
        self.assertEqual(support.limiter._count, 0)

    def test_missing_or_blank_key_is_distinguished_without_exposing_value(self):
        for key in ("", " ", "\n\t"):
            with self.subTest(key_type="blank"):
                self.assert_status(self.support(api_key=key), "key_missing")
        with patch.dict("os.environ", {"OPENAI_API_KEY": ""}):
            self.assert_status(self.support(api_key=None), "key_missing")

    def test_nonempty_invalid_key_reports_only_invalid_category(self):
        for key in ("private-invalid-key", "sk-too-short", '"' + KEY + '"'):
            with self.subTest(key_type="invalid"):
                support = self.support(api_key=key)
                self.assert_status(support, "key_invalid")
                self.assertNotIn(key, json.dumps(support.status()))

    def test_invalid_model_does_not_expose_its_value(self):
        support = self.support(model="private invalid model")
        self.assert_status(support, "model_invalid")
        self.assertNotIn("private invalid model", json.dumps(support.status()))

    def test_disabled_ai_and_storage_failure_are_distinguished(self):
        self.assert_status(self.support(daily_limit=0), "ai_disabled")
        self.assert_status(self.support(storage_error=True), "usage_unavailable")

    def test_reason_precedence_is_deterministic(self):
        self.assert_status(self.support(api_key="", model="bad model", daily_limit=0,
                                        storage_error=True), "key_missing")
        self.assert_status(self.support(api_key="invalid", model="bad model", daily_limit=0,
                                        storage_error=True), "key_invalid")
        self.assert_status(self.support(model="bad model", daily_limit=0,
                                        storage_error=True), "model_invalid")
        self.assert_status(self.support(daily_limit=0, storage_error=True), "ai_disabled")

    def test_ready_status_is_not_a_paid_provider_check(self):
        self.assert_status(self.support(), None)

    def test_status_route_is_uncached_and_config_contract_stays_bool_only(self):
        for support, issue in ((self.support(), None), (self.support(api_key=""), "key_missing")):
            with self.subTest(issue=issue):
                with TestClient(create_app(QuietAutomation, lambda: support)) as client:
                    result = client.get("/api/support/status")
                    self.assertEqual(result.status_code, 200)
                    self.assertEqual(result.json(), {"ai_available": issue is None,
                                                     "configuration_issue": issue})
                    self.assertEqual(result.headers["cache-control"], "no-store")
                    self.assertEqual(result.headers["x-content-type-options"], "nosniff")
                    self.assertNotIn(KEY, result.text)
                    self.assertNotIn(MODEL, result.text)
                    self.assertEqual(client.get("/api/support/config").json(),
                                     {"ai_available": issue is None})
                    self.assertEqual(support.limiter._count, 0)


if __name__ == "__main__":
    unittest.main()
