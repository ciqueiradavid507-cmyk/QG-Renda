"""Testes isolados do conector Woovi. Nenhuma chamada externa real."""
import base64
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

os.environ["DEMO_ONLY"] = "true"
os.environ["COOKIE_SECURE"] = "false"
os.environ["BOOTSTRAP_ADMIN_EMAIL"] = "admin@example.test"
os.environ["BOOTSTRAP_ADMIN_PASSWORD"] = "senha-segura-exclusiva-para-teste"
os.environ.setdefault("DATABASE_PATH", str(Path(tempfile.mkdtemp()) / "test-woovi.sqlite3"))

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from fastapi.testclient import TestClient

import main
import woovi_sandbox


class WooviSandboxTests(unittest.TestCase):
    def setUp(self):
        self.ctx = TestClient(main.app)
        self.client = self.ctx.__enter__()

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def login_admin(self):
        login = self.client.post("/api/auth/login", json={
            "email": "admin@example.test",
            "password": "senha-segura-exclusiva-para-teste",
        })
        self.assertEqual(login.status_code, 200)
        return {"X-CSRF-Token": login.json()["csrf"]}

    def payload(self):
        return {
            "correlation_id": "test_charge_12345678",
            "value_cents": 199,
            "comment": "Cobrança fictícia de teste",
        }

    def test_status_admin_and_safe_defaults(self):
        self.assertEqual(self.client.get("/api/admin/woovi/status").status_code, 401)
        self.login_admin()
        with patch.dict(os.environ, {"WOOVI_SANDBOX_ENABLED": "true"}, clear=False):
            info = self.client.get("/api/admin/woovi/status").json()
        self.assertEqual(info["base_url"], "https://api.woovi-sandbox.com")
        self.assertEqual(info["environment"], "sandbox")
        self.assertFalse(info["outbound_enabled"])
        self.assertFalse(info["real_payments_enabled"])
        self.assertFalse(info["real_transfers_enabled"])
        self.assertFalse(info["wallet_credits_enabled"])

    def test_charges_disabled_by_default(self):
        headers = self.login_admin()
        with patch.dict(os.environ, {
            "WOOVI_SANDBOX_ENABLED": "true",
            "WOOVI_SANDBOX_OUTBOUND_ENABLED": "false",
        }, clear=False):
            response = self.client.post("/api/admin/woovi/sandbox/charges",
                                        json=self.payload(), headers=headers)
        self.assertEqual(response.status_code, 403)

    def test_production_mode_never_allowed(self):
        headers = self.login_admin()
        with patch.dict(os.environ, {
            "DEMO_ONLY": "false", "WOOVI_SANDBOX_ENABLED": "true",
            "WOOVI_SANDBOX_OUTBOUND_ENABLED": "true",
            "WOOVI_SANDBOX_APP_ID": "fake_sandbox_app_id_not_a_real_secret",
        }, clear=False):
            response = self.client.post("/api/admin/woovi/sandbox/charges",
                                        json=self.payload(), headers=headers)
        self.assertEqual(response.status_code, 403)

    def test_admin_required_for_charge(self):
        with patch.dict(os.environ, {
            "WOOVI_SANDBOX_ENABLED": "true",
            "WOOVI_SANDBOX_OUTBOUND_ENABLED": "true",
        }, clear=False):
            result = self.client.post("/api/admin/woovi/sandbox/charges", json=self.payload())
        self.assertEqual(result.status_code, 401)

    def test_charge_uses_only_sandbox_and_cents(self):
        headers = self.login_admin()
        captured = []
        class FakeResponse:
            def raise_for_status(self):
                return None
            def json(self):
                return {"charge": {"status": "ACTIVE", "correlationID": "test_charge_12345678"}}
        class FakeHTTPClient:
            def __init__(self, *args, **kwargs):
                captured.append(kwargs)
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                return None
            async def post(self, path, json=None):
                captured.append((path, json))
                return FakeResponse()
        with patch.dict(os.environ, {
            "WOOVI_SANDBOX_ENABLED": "true",
            "WOOVI_SANDBOX_OUTBOUND_ENABLED": "true",
            "WOOVI_SANDBOX_APP_ID": "fake_sandbox_app_id_not_a_real_secret",
        }, clear=False), patch.object(woovi_sandbox.httpx, "AsyncClient", FakeHTTPClient):
            resp = self.client.post("/api/admin/woovi/sandbox/charges",
                                    json=self.payload(), headers=headers)
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(captured[0]["base_url"], "https://api.woovi-sandbox.com")
        self.assertEqual(captured[1][0], "/api/v1/charge")
        self.assertEqual(captured[1][1]["value"], 199)
        self.assertEqual(captured[1][1]["correlationID"], "test_charge_12345678")
        self.assertEqual(captured[0]["headers"]["Authorization"],
                         "fake_sandbox_app_id_not_a_real_secret")
        self.assertFalse(resp.json()["real_payment"])
        self.assertFalse(resp.json()["wallet_credited"])

    def test_no_webhook_without_signature(self):
        event = {"event": "OPENPIX:CHARGE_COMPLETED"}
        with patch.dict(os.environ, {
            "WOOVI_SANDBOX_ENABLED": "true",
            "WOOVI_SANDBOX_WEBHOOK_PUBLIC_KEY_PEM": "",
        }, clear=False):
            r = self.client.post("/api/integrations/woovi/sandbox/webhook", json=event)
        self.assertEqual(r.status_code, 503)

    def test_valid_rsa_signature_and_idempotency(self):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("ascii")
        correlation = "test_" + uuid4().hex
        raw = json.dumps({
            "event": "OPENPIX:CHARGE_COMPLETED",
            "charge": {"correlationID": correlation, "status": "COMPLETED"},
        }).encode()
        sig = base64.b64encode(key.sign(raw, padding.PKCS1v15(), hashes.SHA256())).decode()
        headers = {"x-webhook-signature": sig, "Content-Type": "application/json"}
        url = "/api/integrations/woovi/sandbox/webhook"
        self.login_admin()
        before = self.client.get("/api/auth/me").json()["user"]["balance_cents"]
        with patch.dict(os.environ, {
            "WOOVI_SANDBOX_ENABLED": "true",
            "WOOVI_SANDBOX_WEBHOOK_PUBLIC_KEY_PEM": pem,
        }, clear=False):
            first = self.client.post(url, content=raw, headers=headers)
            second = self.client.post(url, content=raw, headers=headers)
            bad = self.client.post(url, content=raw+b" ", headers=headers)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertFalse(first.json()["duplicate"])
        self.assertTrue(second.json()["duplicate"])
        self.assertEqual(bad.status_code, 401)
        self.assertFalse(first.json()["wallet_credited"])
        after = self.client.get("/api/auth/me").json()["user"]["balance_cents"]
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
