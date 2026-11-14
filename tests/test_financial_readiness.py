"""Testes da barreira de produção. Não acessam Asaas nem movimentam valores."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ["DEMO_ONLY"] = "true"
os.environ["COOKIE_SECURE"] = "false"
os.environ["BOOTSTRAP_ADMIN_EMAIL"] = "admin@example.test"
os.environ["BOOTSTRAP_ADMIN_PASSWORD"] = "senha-segura-exclusiva-para-teste"
os.environ.setdefault(
    "DATABASE_PATH", str(Path(tempfile.mkdtemp()) / "test-finance.sqlite3")
)

from fastapi.testclient import TestClient
import main
from financial_readiness import financial_readiness_report, require_demonstration_mode


class FinancialReadinessTests(unittest.TestCase):
    def setUp(self):
        self.context = TestClient(main.app)
        self.client = self.context.__enter__()

    def tearDown(self):
        self.context.__exit__(None, None, None)

    def test_demo_mode_required(self):
        require_demonstration_mode(True)
        with self.assertRaisesRegex(RuntimeError, "DEMO_ONLY=true"):
            require_demonstration_mode(False)
        with patch.object(main, "DEMO_ONLY", False):
            with self.assertRaises(RuntimeError):
                main.startup()

    def test_readiness_is_admin_only(self):
        response = self.client.get("/api/admin/finance/readiness")
        self.assertEqual(response.status_code, 401)

    def test_admin_sees_blocked_and_no_secrets(self):
        login = self.client.post("/api/auth/login", json={
            "email": "admin@example.test",
            "password": "senha-segura-exclusiva-para-teste",
        })
        self.assertEqual(login.status_code, 200)
        r = self.client.get("/api/admin/finance/readiness")
        self.assertEqual(r.status_code, 200)
        info = r.json()
        self.assertEqual(info["environment"], "demonstracao")
        self.assertFalse(info["real_payments_enabled"])
        self.assertFalse(info["real_payouts_enabled"])
        self.assertFalse(info["production_ready"])
        self.assertFalse(info["may_enable_production_by_env_flag"])
        self.assertGreater(len(info["checks"]), 4)

    def test_production_env_variables_cannot_unlock_or_leak(self):
        fake = "CHAVE_SENSIVEL_FICTICIA_NAO_USAR"
        with patch.dict(os.environ, {
            "PRODUCTION_PAYMENTS_ENABLED": "true",
            "ASAAS_PRODUCTION_API_KEY": fake,
            "ASAAS_SANDBOX_ENABLED": "true",
        }):
            r = financial_readiness_report(demo_only=True)
            self.assertFalse(r["production_ready"])
            self.assertFalse(r["real_payouts_enabled"])
            self.assertNotIn(fake, json.dumps(r))
            self.assertNotIn("ASAAS_PRODUCTION_API_KEY", json.dumps(r))


if __name__ == "__main__":
    unittest.main()
