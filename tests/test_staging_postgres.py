"""Valida DDL em PostgreSQL descartável do CI. Não processa pagamentos."""
from __future__ import annotations

import hashlib
import os
import unittest
import uuid
from pathlib import Path
from urllib.parse import urlparse

import psycopg

SCHEMA_FILE = Path(__file__).resolve().parents[1] / "db" / "migrations" / "001_staging_inbox.sql"
DSN = os.environ.get("PG_STAGING_TEST_DSN", "")
IS_LOCALHOST = urlparse(DSN).hostname in {"127.0.0.1", "localhost", "::1"}


@unittest.skipUnless(DSN and IS_LOCALHOST, "Exige PostgreSQL de teste local, sem acesso a bancos reais.")
class StagingPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ.get("DEMO_ONLY", "").lower() != "true":
            raise RuntimeError("Testes financeiros só podem rodar com DEMO_ONLY=true.")
        if not IS_LOCALHOST:
            raise RuntimeError("Banco de teste deve estar no localhost.")
        cls.conn = psycopg.connect(DSN, autocommit=True)
        cls.conn.execute(SCHEMA_FILE.read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def test_migration_idempotent(self):
        self.conn.execute(SCHEMA_FILE.read_text(encoding="utf-8"))
        names = {r[0] for r in self.conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'qgr_staging'"
        ).fetchall()}
        self.assertEqual(names, {"webhook_events", "operations"})

    def test_webhook_events_are_deduplicated(self):
        event = "evt_" + uuid.uuid4().hex
        digest = hashlib.sha256(b'{"ficticio":true}').hexdigest()
        statement = """
            INSERT INTO qgr_staging.webhook_events (event_id, event_type, resource_id, payload_sha256)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (event_id) DO UPDATE SET
                delivery_count = qgr_staging.webhook_events.delivery_count + 1,
                last_seen_at = now()
        """
        self.conn.execute(statement, (event, "PAYMENT_RECEIVED", "pay_fake", digest))
        self.conn.execute(statement, (event, "PAYMENT_RECEIVED", "pay_fake", digest))
        count, deliveries = self.conn.execute(
            "SELECT count(*), max(delivery_count) FROM qgr_staging.webhook_events WHERE event_id=%s",
            (event,)
        ).fetchone()
        self.assertEqual((count, deliveries), (1, 2))

    def test_rejects_provider_other_than_sandbox(self):
        event = "evt_" + uuid.uuid4().hex
        digest = hashlib.sha256(b'{"ficticio":true}').hexdigest()
        with self.assertRaises(psycopg.errors.CheckViolation):
            self.conn.execute("""
                INSERT INTO qgr_staging.webhook_events
                (event_id, provider, event_type, payload_sha256)
                VALUES (%s, 'asaas_production', 'PAYMENT_RECEIVED', %s)
            """, (event, digest))

    def test_transfer_idempotency(self):
        unique = "test_" + uuid.uuid4().hex
        first = uuid.uuid4()
        second = uuid.uuid4()
        stmt = """
            INSERT INTO qgr_staging.operations
            (operation_id, idempotency_key, operation_type, amount_cents)
            VALUES (%s, %s, 'transfer_simulation', 100)
            ON CONFLICT (idempotency_key) DO NOTHING
        """
        first_res = self.conn.execute(stmt, (first, unique))
        second_res = self.conn.execute(stmt, (second, unique))
        self.assertEqual(first_res.rowcount, 1)
        self.assertEqual(second_res.rowcount, 0)
        count = self.conn.execute(
            "SELECT COUNT(*) FROM qgr_staging.operations WHERE idempotency_key=%s",
            (unique,)
        ).fetchone()[0]
        self.assertEqual(count, 1)

    def test_no_real_transfer_provider_and_no_negative_amount(self):
        for amount, provider in ((-100, "asaas_sandbox"), (100, "asaas_production")):
            with self.assertRaises(psycopg.errors.CheckViolation):
                self.conn.execute("""
                    INSERT INTO qgr_staging.operations
                    (operation_id, idempotency_key, operation_type, amount_cents, provider)
                    VALUES (%s, %s, 'transfer_simulation', %s, %s)
                """, (uuid.uuid4(), "test_" + uuid.uuid4().hex, amount, provider))

    def test_transaction_rollback(self):
        event = "evt_" + uuid.uuid4().hex
        digest = hashlib.sha256(b"simulacao").hexdigest()
        try:
            with self.conn.transaction():
                self.conn.execute("""
                    INSERT INTO qgr_staging.webhook_events
                    (event_id, event_type, payload_sha256)
                    VALUES (%s, 'PAYMENT_CREATED', %s)
                """, (event, digest))
                raise RuntimeError("Falha simulada")
        except RuntimeError:
            pass
        row = self.conn.execute(
            "SELECT count(*) FROM qgr_staging.webhook_events WHERE event_id=%s", (event,)
        ).fetchone()[0]
        self.assertEqual(row, 0)


if __name__ == "__main__":
    unittest.main()
