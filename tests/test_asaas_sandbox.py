"""Testes Asaas exclusivamente em Sandbox; nenhum pagamento real é executado."""
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
os.environ.setdefault("DATABASE_PATH", str(Path(tempfile.mkdtemp()) / "test-asaas.sqlite3"))

from fastapi.testclient import TestClient
import main
import asaas_sandbox


class SandboxIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.context = TestClient(main.app)
        self.client = self.context.__enter__()

    def tearDown(self):
        self.context.__exit__(None, None, None)

    def admin_headers(self):
        login = self.client.post("/api/auth/login", json={
            "email": "admin@example.test",
            "password": "senha-segura-exclusiva-para-teste",
        })
        self.assertEqual(login.status_code, 200)
        return {"X-CSRF-Token": login.json()["csrf"]}

    def test_status_is_admin_only_and_production_disabled(self):
        self.assertEqual(self.client.get("/api/admin/asaas/status").status_code, 401)
        self.admin_headers()
        with patch.dict(os.environ, {"ASAAS_SANDBOX_ENABLED": "true"}, clear=False):
            result = self.client.get("/api/admin/asaas/status")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["environment"], "sandbox")
        self.assertFalse(result.json()["real_payments_enabled"])
        self.assertFalse(result.json()["wallet_credit_from_webhooks"])
        self.assertEqual(asaas_sandbox.ASAAS_SANDBOX_BASE, "https://api-sandbox.asaas.com/v3")

    def test_charge_blocked_without_explicit_outbound_and_sandbox_key(self):
        headers = self.admin_headers()
        body = {"customer_id": "cus_123456789", "amount_cents": 100,
                "reference": "test_12345678", "description": "Teste Pix"}
        with patch.dict(os.environ, {"ASAAS_SANDBOX_ENABLED": "true",
                                      "ASAAS_SANDBOX_OUTBOUND_ENABLED": "false"}, clear=False):
            self.assertEqual(self.client.post(
                "/api/admin/asaas/sandbox/charges", json=body, headers=headers
            ).status_code, 403)
        with patch.dict(os.environ, {
            "ASAAS_SANDBOX_ENABLED": "true",
            "ASAAS_SANDBOX_OUTBOUND_ENABLED": "true",
            "ASAAS_SANDBOX_API_KEY": "$aact_prod_NUNCA_USAR_EM_TESTES",
        }, clear=False):
            self.assertEqual(self.client.post(
                "/api/admin/asaas/sandbox/charges", json=body, headers=headers
            ).status_code, 503)

    def test_sandbox_request_uses_only_sandbox_host(self):
        headers = self.admin_headers()
        calls = []

        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {"id": "pay_sandbox_123", "status": "PENDING"}

        class FakeClient:
            def __init__(self, *args, **kwargs):
                calls.append(kwargs)
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                return None
            async def post(self, path, json=None):
                calls.append((path, json))
                return FakeResponse()

        with patch.dict(os.environ, {
            "ASAAS_SANDBOX_ENABLED": "true", "ASAAS_SANDBOX_OUTBOUND_ENABLED": "true",
            "ASAAS_SANDBOX_API_KEY": "$aact_hmlg_CHAVE_FICTICIA_SOMENTE_TESTE_123456789",
        }, clear=False), patch.object(asaas_sandbox.httpx, "AsyncClient", FakeClient):
            r = self.client.post("/api/admin/asaas/sandbox/charges", json={
                "customer_id": "cus_123456789", "amount_cents": 199,
                "reference": "test_abcdefgh", "description": "Teste isolado",
            }, headers=headers)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["id"], "pay_sandbox_123")
        self.assertFalse(r.json()["real_payment"])
        self.assertEqual(calls[0]["base_url"], "https://api-sandbox.asaas.com/v3")
        self.assertEqual(calls[1][0], "/payments")
        self.assertEqual(calls[1][1]["value"], 1.99)

    def test_transfers_disabled_even_if_charge_tests_enabled(self):
        headers = self.admin_headers()
        with patch.dict(os.environ, {"ASAAS_SANDBOX_ENABLED": "true",
                                      "ASAAS_SANDBOX_OUTBOUND_ENABLED": "true",
                                      "ASAAS_SANDBOX_TRANSFER_TESTS_ENABLED": "false"}, clear=False):
            result = self.client.post("/api/admin/asaas/sandbox/transfers", json={
                "pix_key": "teste@example.com", "pix_key_type": "EMAIL", "amount_cents": 100,
                "reference": "teste_abc123",
            }, headers=headers)
        self.assertEqual(result.status_code, 403)

    def test_webhook_auth_and_idempotency_never_credit_wallet(self):
        headers = self.admin_headers()
        before = self.client.get("/api/auth/me").json()["user"]["balance_cents"]
        event_id = "evt_" + uuid4().hex
        payload = {"id": event_id, "event": "PAYMENT_RECEIVED",
                   "payment": {"id": "pay_ficticio", "value": 10000}}
        token = "token_WEBHOOK_sandbox_exclusivo_para_testes_123456"
        with patch.dict(os.environ, {"ASAAS_SANDBOX_ENABLED": "true",
                                      "ASAAS_SANDBOX_WEBHOOK_TOKEN": token}, clear=False):
            url = "/api/integrations/asaas/sandbox/webhook"
            self.assertEqual(self.client.post(url, json=payload,
                                              headers={"asaas-access-token": "errado"}).status_code, 401)
            one = self.client.post(url, json=payload, headers={"asaas-access-token": token})
            two = self.client.post(url, json=payload, headers={"asaas-access-token": token})
        self.assertEqual(one.status_code, 200)
        self.assertFalse(one.json()["duplicate"])
        self.assertEqual(two.status_code, 200)
        self.assertTrue(two.json()["duplicate"])
        self.assertFalse(one.json()["wallet_credited"])
        after = self.client.get("/api/auth/me").json()["user"]["balance_cents"]
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
