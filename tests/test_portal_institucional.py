"""Testes do novo portal independente. Não acessam serviços externos."""
import unittest
from fastapi.testclient import TestClient
from portal_institucional import app


class InstitutionalPortalTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()

    def test_health_explicitly_demo(self):
        r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["demo_only"])
        self.assertFalse(r.json()["payments_enabled"])
        self.assertFalse(r.json()["official_government_service"])
        self.assertFalse(r.json()["personal_data_collection_enabled"])

    def test_config_no_identity_or_payments(self):
        r = self.client.get("/api/config")
        self.assertEqual(r.status_code, 200)
        for key in ("payments_enabled", "collects_cpf", "collects_passwords",
                    "government_affiliation"):
            self.assertFalse(r.json()[key])

    def test_home_includes_clear_disclaimer(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        body = r.text
        self.assertIn("Não pertence à Receita Federal", body)
        self.assertIn("https://www.gov.br/receitafederal/pt-br", body)
        self.assertIn("Portal independente", body)
        self.assertIn("sem criar uma conta", body)
        self.assertIn('id="busca"', body)
        self.assertIn('id="nav-toggle"', body)
        self.assertIn("aria-pressed", body)
        self.assertIn("[hidden]{display:none!important}", body)
        self.assertNotIn("<form", body.lower())
        self.assertNotIn('name="cpf"', body.lower())
        self.assertNotIn('name="password"', body.lower())
        self.assertNotIn("asaas.com", body.lower())
        self.assertNotIn("woovi-sandbox.com", body.lower())

    def test_security_headers(self):
        r = self.client.get("/")
        self.assertEqual(r.headers["x-frame-options"], "DENY")
        self.assertEqual(r.headers["x-content-type-options"], "nosniff")
        self.assertIn("form-action 'none'", r.headers["content-security-policy"])
        self.assertIn("connect-src 'none'", r.headers["content-security-policy"])


if __name__ == "__main__":
    unittest.main()
