"""QG RENDA | Edição Institucional — portal informativo independente.

Este site NÃO pertence à Receita Federal, NÃO coleta documentos, não possui
login gov.br, não processa valores e não altera a plataforma principal.
"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent
app = FastAPI(title="QG RENDA — Portal Independente", docs_url=None, redoc_url=None, openapi_url=None)
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


@app.get("/")
def index():
    return FileResponse(ROOT / "institutional_site" / "index.html", media_type="text/html", headers={
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "no-referrer",
        "Content-Security-Policy": (
            "default-src 'none'; style-src 'unsafe-inline'; "
            "script-src 'unsafe-inline'; img-src 'self' data:; "
            "base-uri 'none'; form-action 'none'; frame-ancestors 'none'; "
            "connect-src 'none'"
        ),
    })
