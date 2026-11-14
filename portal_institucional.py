"""Portal informativo independente, com manutenção de fontes e sem dados de visitantes."""
import asyncio
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from portal_automation import AutomationManager

ROOT = Path(__file__).resolve().parent


def create_app(automation_factory=AutomationManager):
    @asynccontextmanager
    async def lifespan(current_app):
        manager = automation_factory()
        current_app.state.automation_manager = manager
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
