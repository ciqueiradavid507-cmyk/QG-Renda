"""Portal independente, com manutenção de fontes e suporte sem persistir conversas."""
import asyncio
import json
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from portal_automation import AutomationManager
from ai_support import AISupport

ROOT = Path(__file__).resolve().parent


def create_app(automation_factory=AutomationManager, support_factory=AISupport):
    @asynccontextmanager
    async def lifespan(current_app):
        manager = automation_factory()
        current_app.state.automation_manager = manager
        current_app.state.ai_support = support_factory()
        periodic = asyncio.create_task(manager.periodic_loop())
        try:
            yield
        finally:
            periodic.cancel()
            try:
                with suppress(asyncio.CancelledError):
                    await periodic
            finally:
                await manager.close()

    app = FastAPI(title="QG RENDA — Portal Independente", docs_url=None,
                  redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.mount("/assets", StaticFiles(directory=ROOT / "institutional_site" / "assets"), name="assets")

    @app.get("/health")
    def health():
        return {
            "ok": True,
            "project": "QG RENDA Portal Independente",
            "official_government_service": False,
            "demo_only": True,
            "payments_enabled": False,
            "personal_data_collection_enabled": False,
        }

    @app.get("/api/config")
    def config():
        return {
            "site_name": "QG RENDA — Portal Independente",
            "demo_only": True,
            "government_affiliation": False,
            "payments_enabled": False,
            "collects_cpf": False,
            "collects_passwords": False,
        }

    @app.get("/api/automation")
    async def automation(wait: bool = False):
        manager = app.state.automation_manager
        if wait:
            try:
                result = await asyncio.wait_for(manager.refresh_if_due(wait=True), timeout=40)
            except asyncio.TimeoutError:
                result = manager.snapshot()
        else:
            result = await manager.refresh_if_due(wait=False)
        return JSONResponse(result, headers={"Cache-Control": "no-store",
                                             "X-Content-Type-Options": "nosniff"})

    @app.get("/api/support/config")
    async def support_config():
        return JSONResponse(app.state.ai_support.config(), headers={
            "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
        })

    @app.get("/api/support/status")
    async def support_status():
        return JSONResponse(app.state.ai_support.status(), headers={
            "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
        })

    @app.post("/api/support/respond")
    async def support_respond(request: Request):
        def error(reason, status=400):
            return JSONResponse({"mode": "local", "reply": "Use o suporte local para continuar esta orientação.",
                                 "links": [], "reason": reason}, status_code=status,
                                headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})

        origin = request.headers.get("origin")
        allowed_origins = {"https://qg-renda-portal-independente.onrender.com", str(request.base_url).rstrip("/")}
        if origin and origin not in allowed_origins:
            return error("origin_not_allowed", 403)
        if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
            return error("json_required", 415)
        try:
            length = int(request.headers.get("content-length", "0"))
            if length > 8192 or length < 0:
                return error("request_too_large", 413)
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > 8192:
                    return error("request_too_large", 413)
            payload = json.loads(body)
        except (ValueError, UnicodeError):
            return error("invalid_request")
        if not isinstance(payload, dict) or set(payload) - {"message", "history"}:
            return error("invalid_request")
        message, history = payload.get("message"), payload.get("history", [])
        if not isinstance(message, str) or not 1 <= len(message.strip()) <= 300:
            return error("invalid_request")
        if not isinstance(history, list) or len(history) > 4:
            return error("invalid_request")
        for item in history:
            if (not isinstance(item, dict) or set(item) != {"role", "content"}
                    or not isinstance(item.get("role"), str)
                    or item.get("role") not in {"user", "assistant"}
                    or not isinstance(item.get("content"), str)
                    or not 1 <= len(item["content"].strip()) <= 300):
                return error("invalid_request")
        try:
            result = await app.state.ai_support.respond(
                message.strip(), history, request.client.host if request.client else "unknown")
        except Exception:
            return error("support_unavailable", 503)
        reason = result.get("reason", "")
        status = 200
        if reason in {"not_configured", "provider_error", "provider_timeout", "support_unavailable",
                      "usage_unavailable", "unsafe_response"}:
            status = 503
        elif reason in {"rate_limit", "global_rate_limit", "provider_rate_limited", "daily_limit", "busy"}:
            status = 429
        return JSONResponse(result, status_code=status, headers={
            "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
        })

    @app.get("/")
    def index():
        return FileResponse(ROOT / "institutional_site" / "index.html", media_type="text/html", headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": (
                "default-src 'none'; style-src 'unsafe-inline'; "
                "script-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                "base-uri 'none'; form-action 'none'; frame-ancestors 'none'; "
                "connect-src 'self'"
            ),
        })

    return app


app = create_app()
