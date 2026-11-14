"""Woovi Sandbox connector for QG RENDA; safe by default.

Only sandbox charges are supported and external calls are disabled by default.
Webhooks cannot credit wallets, mark withdrawals paid, or trigger transfers.
This module contains NO production Woovi API endpoints.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from typing import Any

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

# Literal host/path; never configurable via env or user input.
WOOVI_SANDBOX_BASE = "https://api.woovi-sandbox.com"
WOOVI_SANDBOX_CHARGE_PATH = "/api/v1/charge"
MAX_WEBHOOK_BYTES = 65536


def enabled(name: str) -> bool:
    return os.environ.get(name, "false").strip().lower() == "true"


def only_sandbox() -> None:
    if not enabled("DEMO_ONLY") or not enabled("WOOVI_SANDBOX_ENABLED"):
        raise HTTPException(403, "Woovi disponível exclusivamente no modo demonstrativo Sandbox.")


def sandbox_app_id() -> str | None:
    app_id = os.environ.get("WOOVI_SANDBOX_APP_ID", "").strip()
    # Woovi credentials are opaque. Production credentials fail against the
    # sandbox host, and this connector cannot target production.
    if len(app_id) < 24 or len(app_id) > 2048 or any(ch.isspace() for ch in app_id):
        return None
    return app_id


def sandbox_public_key():
    pem = os.environ.get("WOOVI_SANDBOX_WEBHOOK_PUBLIC_KEY_PEM", "").strip()
    if not pem:
        return None
    try:
        public_key = serialization.load_pem_public_key(pem.replace("\\n", "\n").encode("ascii"))
        if not isinstance(public_key, rsa.RSAPublicKey) or public_key.key_size < 2048:
            return None
        return public_key
    except (ValueError, TypeError, UnicodeEncodeError):
        return None


class SandboxCharge(BaseModel):
    value_cents: int = Field(ge=100, le=10000)
    correlation_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    comment: str = Field(default="QG RENDA - teste fictício", min_length=5, max_length=100)


def verify_sandbox_signature(body: bytes, signature: str | None) -> bool:
    public_key = sandbox_public_key()
    if public_key is None or not signature or len(signature) > 1024:
        return False
    try:
        sig = base64.b64decode(signature, validate=True)
        public_key.verify(sig, body, padding.PKCS1v15(), hashes.SHA256())
        return True
    except (binascii.Error, ValueError, InvalidSignature):
        return False


async def request_sandbox_charge(payload: dict[str, Any]) -> dict[str, Any]:
    if not enabled("WOOVI_SANDBOX_OUTBOUND_ENABLED"):
        raise HTTPException(403, "Chamadas externas da Woovi Sandbox desativadas.")
    app_id = sandbox_app_id()
    if app_id is None:
        raise HTTPException(503, "Configure um AppID exclusivo da Woovi Sandbox no servidor.")
    try:
        async with httpx.AsyncClient(
            base_url=WOOVI_SANDBOX_BASE,
            timeout=12.0,
            follow_redirects=False,
            headers={
                "Authorization": app_id,
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "QGRenda-Sandbox/1.0",
            },
        ) as client:
            result = await client.post(WOOVI_SANDBOX_CHARGE_PATH, json=payload)
            result.raise_for_status()
            response_data = result.json()
    except (httpx.HTTPError, ValueError):
        # Avoid reflecting provider responses: they may contain sensitive data.
        raise HTTPException(502, "Falha ao consultar Woovi Sandbox; confira o painel de testes.")
    if not isinstance(response_data, dict) or not isinstance(response_data.get("charge"), dict):
        raise HTTPException(502, "Resposta inesperada da Woovi Sandbox.")
    return response_data


def install_woovi_sandbox(app, connect, admin_user) -> None:
    router = APIRouter()

    @router.get("/api/admin/woovi/status")
    def status(admin=Depends(admin_user)):
        return {
            "provider": "woovi",
            "environment": "sandbox",
            "base_url": WOOVI_SANDBOX_BASE,
            "sandbox_enabled": enabled("DEMO_ONLY") and enabled("WOOVI_SANDBOX_ENABLED"),
            "outbound_enabled": (enabled("DEMO_ONLY") and enabled("WOOVI_SANDBOX_ENABLED")
                                 and enabled("WOOVI_SANDBOX_OUTBOUND_ENABLED")),
            "app_id_configured": sandbox_app_id() is not None,
            "webhook_verification_configured": sandbox_public_key() is not None,
            "real_payments_enabled": False,
            "real_transfers_enabled": False,
            "wallet_credits_enabled": False,
        }

    @router.post("/api/admin/woovi/sandbox/charges")
    async def create_sandbox_charge(body: SandboxCharge, admin=Depends(admin_user)):
        only_sandbox()
        result = await request_sandbox_charge({
            "value": body.value_cents,  # Woovi expects cents, not reais.
            "correlationID": body.correlation_id,
            "comment": body.comment,
        })
        charge = result["charge"]
        return {
            "provider": "woovi",
            "environment": "sandbox",
            "correlation_id": body.correlation_id,
            "status": str(charge.get("status", "UNKNOWN"))[:32],
            "sandbox_charge_created": True,
            "real_payment": False,
            "wallet_credited": False,
        }

    @router.post("/api/integrations/woovi/sandbox/webhook")
    async def webhook(request: Request):
        only_sandbox()
        if sandbox_public_key() is None:
            raise HTTPException(503, "Chave pública do webhook Sandbox não configurada.")
        raw = await request.body()
        if len(raw) > MAX_WEBHOOK_BYTES:
            raise HTTPException(413, "Webhook excede o tamanho permitido.")
        if not verify_sandbox_signature(raw, request.headers.get("x-webhook-signature")):
            raise HTTPException(401, "Assinatura Woovi Sandbox inválida.")
        try:
            event = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise HTTPException(400, "JSON inválido.")
        if not isinstance(event, dict):
            raise HTTPException(400, "Evento inválido.")
        event_type = event.get("event")
        if not isinstance(event_type, str) or not event_type.startswith("OPENPIX:") or len(event_type) > 80:
            raise HTTPException(400, "Tipo de evento inválido.")
        charge = event.get("charge") if isinstance(event.get("charge"), dict) else {}
        correlation = charge.get("correlationID") or event.get("correlationID")
        if not isinstance(correlation, str) or len(correlation) > 128:
            correlation = ""
        digest = hashlib.sha256(raw).hexdigest()
        dedupe_key = hashlib.sha256(
            (event_type + ":" + correlation).encode("utf-8") if correlation else raw
        ).hexdigest()
        with closing(connect()) as con:
            con.execute("""CREATE TABLE IF NOT EXISTS woovi_sandbox_events (
                id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                correlation_id TEXT,
                body_sha256 TEXT NOT NULL,
                received_at TEXT NOT NULL
            )""")
            cursor = con.execute(
                "INSERT OR IGNORE INTO woovi_sandbox_events "
                "(id,event_type,correlation_id,body_sha256,received_at) VALUES (?,?,?,?,?)",
                (dedupe_key, event_type, correlation, digest,
                 datetime.now(timezone.utc).isoformat()),
            )
        # Absolutely no link to users, balances, withdrawals or financial ledger.
        return {"received": True, "duplicate": cursor.rowcount == 0, "wallet_credited": False}

    @router.get("/api/admin/woovi/sandbox/events")
    def list_events(admin=Depends(admin_user)):
        only_sandbox()
        with closing(connect()) as con:
            con.execute("""CREATE TABLE IF NOT EXISTS woovi_sandbox_events (
                id TEXT PRIMARY KEY, event_type TEXT NOT NULL,
                correlation_id TEXT, body_sha256 TEXT NOT NULL, received_at TEXT NOT NULL
            )""")
            rows = con.execute(
                "SELECT event_type, correlation_id, received_at FROM woovi_sandbox_events "
                "ORDER BY received_at DESC LIMIT 50"
            ).fetchall()
        return {"environment": "sandbox", "events": [dict(r) for r in rows]}

    app.include_router(router)
