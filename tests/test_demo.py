import os
import tempfile
import unittest
from pathlib import Path

os.environ["DEMO_ONLY"] = "true"
os.environ["COOKIE_SECURE"] = "false"
os.environ["BOOTSTRAP_ADMIN_EMAIL"] = "admin@example.test"
os.environ["BOOTSTRAP_ADMIN_PASSWORD"] = "senha-segura-exclusiva-para-teste"
os.environ["DATABASE_PATH"] = str(Path(tempfile.mkdtemp()) / "test.sqlite3")

from fastapi.testclient import TestClient
import main


class DemoTests(unittest.TestCase):
    def setUp(self):
        self.ctx = TestClient(main.app)
        self.client = self.ctx.__enter__()

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def test_health_and_config(self):
        self.assertEqual(self.client.get("/api/health").status_code, 200)
        self.assertTrue(self.client.get("/api/config").json()["demo_only"])
        self.assertFalse(self.client.get("/api/config").json()["automatic_payments"])

    def test_static_pages_load(self):
        for path in ("/", "/termos", "/privacidade", "/assets/style.css", "/assets/app.js"):
            self.assertEqual(self.client.get(path).status_code, 200, path)

    def test_withdrawals_disabled(self):
        login = self.client.post("/api/auth/login", json={
            "email": "admin@example.test",
            "password": "senha-segura-exclusiva-para-teste",
        })
        self.assertEqual(login.status_code, 200)
        csrf = login.json()["csrf"]
        r = self.client.post("/api/withdrawals", json={"amount_cents": 2000}, headers={"X-CSRF-Token": csrf})
        self.assertEqual(r.status_code, 403)

    def test_paid_tasks_disabled(self):
        login = self.client.post("/api/auth/login", json={
            "email": "admin@example.test",
            "password": "senha-segura-exclusiva-para-teste",
        })
        self.assertEqual(login.status_code, 200)
        csrf = login.json()["csrf"]
        r = self.client.post("/api/admin/tasks", json={
            "title": "Teste de tarefa remunerada",
            "description": "Tentativa de criar uma tarefa remunerada no ambiente gratuito.",
            "sponsor": "Teste",
            "demo": False,
            "reward_cents": 100,
            "budget_cents": 100,
            "funding_confirmed": True,
        }, headers={"X-CSRF-Token": csrf})
        self.assertEqual(r.status_code, 403)


if __name__ == "__main__":
    unittest.main()
