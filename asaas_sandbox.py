"""Integração ISOLADA com Asaas Sandbox. Nunca envia requisições à produção.

Este módulo NÃO credita carteiras, NÃO confirma receita, NÃO processa
saques reais e não deve ser reutilizado como um gateway de produção.
"""
from __future__ import annotations

import hmac
import json
import os
import re
from datetime import date, timedelta, datetime, timezone
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

ASAAS_SANDBOX_BASE = "https://api-sandbox.asaas.com/v3"
ASAAS_SANDBOX_HOST = "api-sandbox.asaas.com"


def _yes(name: str) -> bool:
    return os.environ.get(name, "false").strip().lower() == "true"


def _sandbox_only() -> None:
    # Segurança por negação: recusa funcionar se o site sair do modo demo.
    if not _yes("DEMO_ONLY") or not _yes("ASAAS_SANDBOX_ENABLED"):
        raise HTTPException(403, "Integração disponível somente em ambiente demonstrativo Sandbox.")


def _sandbox_key() -> str | None:
    key = os.environ.get("ASAAS_SANDBOX_API_KEY", "").strip()
    # Uma chave de produção não pode ser utilizada aqui nem por engano.
    if not key.startswith("$aact_hmlg_") or len(key) < 20:
        return None
    return key


def _webhook_token() -> str | None:
    token = os.environ.get("ASAAS_SANDBOX_WEBHOOK_TOKEN", "")
    if 32 <= len(token) <= 255 and not any(ch.isspace() for ch in token) and token != _sandbox_key():
        return token
    return None


class SandboxCharge(BaseModel):
    customer_id: str = Field(pattern=r"^cus_[a-zA-Z0-9_-]{5,80}$", max_length=84)
    amount_cents: int = Field(ge=100, le=10000)
    reference: str = Field(pattern=r"^[a-zA-Z0-9_-]{8,64}$")
    description: str = Field(default="Cobrança de teste QG RENDA", min_length=6, max_length=120)


class SandboxTransfer(BaseModel):
    pix_key: str = Field(min_length=5, max_length=120)
    pix_key_type: Literal["CPF", "CNPJ", "EMAIL", "PHONE", "EVP"]
    amount_cents: int = Field(ge=100, le=10000)
    reference: str = Field(pattern=r"^[a-zA-Z0-9_-]{8,64}$")


async def _asaas_post(path: str, payload: dict) -> dict:
    # Endpoint e domínio fixos, sem possibilidade de configurar host de produção.
    if path not in ("/payments", "/transfers"):
        raise HTTPException(400, "Operação de Sandbox não permitida.")
    if not _yes("ASAAS_SANDBOX_OUTBOUND_ENABLED"):
        raise HTTPException(403, "Chamadas externas de Sandbox ainda desativadas.")
    key = _sandbox_key()
    if key is None:
        raise HTTPException(503, "Configure uma chave exclusiva do Asaas Sandbox no Render.")
    headers = {
        "access_token": key,
        "User-Agent": "QGRenda-Sandbox/1.0",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(
            base_url=ASAAS_SANDBOX_BASE, headers=headers, timeout=12.0,
            follow_redirects=False,
        ) as client:
            response = await client.post(path, json=payload)
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, ValueError):
        # Não retornamos body, headers ou detalhes capazes de vazar segredos.
        raise HTTPException(502, "Falha na comunicação com Asaas Sandbox. Consulte o painel Asaas.")
    if not isinstance(data, dict) or not isinstance(data.get("id"), str):
        raise HTTPException(502, "Resposta inesperada do Asaas Sandbox.")
    return data


def install_asaas_sandbox(app, connect, admin_user):
    router = APIRouter()

    @router.get("/api/admin/asaas/status")
    def status(admin=Depends(admin_user)):
        return {
            "provider": "asaas",
            "environment": "sandbox",
            "sandbox_base": ASAAS_SANDBOX_BASE,
            "demo_only": _yes("DEMO_ONLY"),
            "sandbox_enabled": _yes("DEMO_ONLY") and _yes("ASAAS_SANDBOX_ENABLED"),
            "sandbox_key_configured": _sandbox_key() is not None,
            "webhook_token_configured": _webhook_token() is not None,
            "outbound_enabled": _yes("DEMO_ONLY") and _yes("ASAAS_SANDBOX_OUTBOUND_ENABLED"),
            "transfer_tests_enabled": _yes("DEMO_ONLY") and _yes("ASAAS_SANDBOX_TRANSFER_TESTS_ENABLED"),
            "real_payments_enabled": False,
            "wallet_credit_from_webhooks": False,
        }

    @router.post("/api/admin/asaas/sandbox/charges")
    async def sandbox_charge(body: SandboxCharge, admin=Depends(admin_user)):
        _sandbox_only()
        payment = await _asaas_post("/payments", {
            "customer": body.customer_id,
            "billingType": "PIX",
            "value": round(body.amount_cents / 100, 2),
            "dueDate": (date.today() + timedelta(days=1)).isoformat(),
            "description": body.description,
            "externalReference": body.reference,
        })
        return {
            "environment": "sandbox", "id": payment["id"],
            "status": payment.get("status"),
            "wallet_credited": False, "real_payment": False,
        }

    @router.post("/api/admin/asaas/sandbox/transfers")
    async def sandbox_transfer(body: SandboxTransfer, admin=Depends(admin_user)):
        _sandbox_only()
        if not _yes("ASAAS_SANDBOX_TRANSFER_TESTS_ENABLED"):
            raise HTTPException(403, "Testes de transferência Sandbox desativados.")
        transfer = await _asaas_post("/transfers", {
            "value": round(body.amount_cents / 100, 2),
            "pixAddressKey": body.pix_key,
            "pixAddressKeyType": body.pix_key_type,
            "description": "Transferência fictícia - QG RENDA Sandbox",
            "externalReference": body.reference,
        })
        return {
            "environment": "sandbox", "id": transfer["id"],
            "status": transfer.get("status"),
            "real_transfer": False, "withdrawal_processed": False,
        }

    @router.post("/api/integrations/asaas/sandbox/webhook")
    async def webhook(request: Request, token: str | None = Header(default=None, alias="asaas-access-token")):
        _sandbox_only()
        expected = _webhook_token()
        if not expected:
            raise HTTPException(503, "Webhook do Sandbox não configurado.")
        if token is None or not hmac.compare_digest(token, expected):
            raise HTTPException(401, "Webhook não autorizado.")
        if request.headers.get("content-length", "").isdigit() and int(request.headers["content-length"]) > 65536:
            raise HTTPException(413, "Evento grande demais.")
        payload = await request.body()
        if len(payload) > 65536:
            raise HTTPException(413, "Evento grande demais.")
        try:
            event = json.loads(payload)
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise HTTPException(400, "JSON inválido.")
        if not isinstance(event, dict):
            raise HTTPException(400, "Evento inválido.")
        event_id, event_type = event.get("id"), event.get("event")
        if (not isinstance(event_id, str) or not 1 <= len(event_id) <= 128 or
                not isinstance(event_type, str) or not 1 <= len(event_type) <= 80):
            raise HTTPException(400, "ID ou tipo de evento inválido.")
        resource = event.get("payment") or event.get("transfer") or {}
        resource_id = resource.get("id") if isinstance(resource, dict) else None
        resource_id = resource_id if isinstance(resource_id, str) else None
        with connect() as con:
            con.execute("""CREATE TABLE IF NOT EXISTS asaas_sandbox_events (
                id TEXT PRIMARY KEY, event_type TEXT NOT NULL,
                resource_id TEXT, received_at TEXT NOT NULL
            )""")
            cursor = con.execute(
                "INSERT OR IGNORE INTO asaas_sandbox_events (id,event_type,resource_id,received_at) VALUES (?,?,?,?)",
                (event_id, event_type, resource_id, datetime.now(timezone.utc).isoformat())
            )
        # Intencional: não altera saldos, tarefas, saques nem ledger.
        return {"received": True, "duplicate": cursor.rowcount == 0, "wallet_credited": False}

    @router.get("/api/admin/asaas/sandbox/events")
    def events(admin=Depends(admin_user)):
        with connect() as con:
            con.execute("""CREATE TABLE IF NOT EXISTS asaas_sandbox_events (
                id TEXT PRIMARY KEY, event_type TEXT NOT NULL,
                resource_id TEXT, received_at TEXT NOT NULL
            )""")
            rows = con.execute(
                "SELECT id,event_type,resource_id,received_at FROM asaas_sandbox_events ORDER BY received_at DESC LIMIT 50"
            ).fetchall()
        return {"environment": "sandbox", "events": [dict(row) for row in rows]}

    app.include_router(router)
