"""Periodic checks of an authored set of public sources, without visitor data.

Only source metadata is refreshed. Editorial instructions and the approved list
of URLs remain versioned code/content. Upstream failure never replaces a last
known description with an error page.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from html.parser import HTMLParser
import json
import logging
from pathlib import Path
import re
import tempfile
from typing import Callable, Sequence
from urllib.parse import urljoin, urlsplit

import httpx


LOG = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent
ALLOWED_HOSTS = frozenset({"www.gov.br", "www.bcb.gov.br", "cartilha.cert.br"})
INTERVAL_SECONDS = 6 * 60 * 60
DEFAULT_CACHE_PATH = Path(tempfile.gettempdir()) / "qg-renda-automation" / "sources.json"
MAX_HTML_BYTES = 1024 * 1024
MAX_PDF_BYTES = 64 * 1024


def _allowed_url(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        return (parsed.scheme == "https" and parsed.hostname in ALLOWED_HOSTS
                and parsed.port in (None, 443) and not parsed.username
                and not parsed.password)
    except (TypeError, ValueError):
        return False


def _clean(value: str, limit: int = 400) -> str:
    return " ".join(value.split())[:limit]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _date(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result.astimezone(timezone.utc) if result.tzinfo else None
    except ValueError:
        return None


@dataclass(frozen=True)
class SourceSpec:
    id: str
    guide_id: str | None
    name: str
    url: str
    description: str
    kind: str = "html"

    def __post_init__(self):
        if not _allowed_url(self.url) or self.kind not in {"html", "pdf"}:
            raise ValueError("A fonte deve usar HTTPS e um domínio permitido")
        if not re.fullmatch(r"[a-z0-9_-]{1,40}", self.id):
            raise ValueError("Identificador de fonte inválido")


DEFAULT_SOURCES = tuple(SourceSpec(**item) for item in json.loads(
    (ROOT / "institutional_site" / "data" / "automation_sources.json").read_text(encoding="utf-8")
))


class SourceHTML(HTMLParser):
    """Read metadata and limited headings; never execute or reuse upstream HTML."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.description = ""
        self.headings: list[str] = []
        self.paragraph = ""
        self._tag: str | None = None
        self._parts: list[str] = []
        self._ignored = 0
        self._in_main = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in {"script", "style", "nav", "footer", "noscript"}:
            self._ignored += 1
        if tag == "main":
            self._in_main += 1
        if tag == "meta":
            key = (attrs.get("name") or attrs.get("property") or "").lower()
            if key in {"description", "og:description"} and not self.description:
                self.description = _clean(attrs.get("content") or "")
        if self._ignored:
            return
        if tag == "title" or (self._in_main and tag in {"h1", "h2", "h3", "p"}):
            if self._tag is None:
                self._tag, self._parts = tag, []

    def handle_endtag(self, tag):
        if tag == self._tag:
            value = _clean(" ".join(self._parts))
            if tag == "title":
                self.title = value[:200]
            elif tag in {"h1", "h2", "h3"} and value and len(self.headings) < 5:
                self.headings.append(value[:160])
            elif tag == "p" and len(value) >= 30 and not self.paragraph:
                self.paragraph = value
            self._tag, self._parts = None, []
        if tag in {"script", "style", "nav", "footer", "noscript"}:
            self._ignored = max(0, self._ignored - 1)
        if tag == "main":
            self._in_main = max(0, self._in_main - 1)

    def handle_data(self, data):
        if self._tag and not self._ignored:
            self._parts.append(data)


class SourceFailure(Exception):
    def __init__(self, code: str, http_status: int | None = None):
        self.code, self.http_status = code, http_status


class AutomationManager:
    def __init__(self, specs: Sequence[SourceSpec] = DEFAULT_SOURCES,
                 cache_path: Path | None = DEFAULT_CACHE_PATH,
                 transport: httpx.AsyncBaseTransport | None = None,
                 clock: Callable[[], datetime] = _utcnow,
                 interval_seconds: float = INTERVAL_SECONDS,
                 request_timeout: float = 8.0,
                 source_wall_timeout: float = 16.0):
        self.specs = tuple(specs)
        if len({s.id for s in self.specs}) != len(self.specs):
            raise ValueError("Fontes duplicadas")
        self.cache_path = Path(cache_path) if cache_path is not None else None
        self.transport, self.clock = transport, clock
        self.interval_seconds, self.request_timeout = interval_seconds, request_timeout
        self.source_wall_timeout = source_wall_timeout
        self._records = {spec.id: self._initial(spec) for spec in self.specs}
        self._last_started: datetime | None = None
        self._last_checked: datetime | None = None
        self._last_error: str | None = None
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._load_cache()

    @staticmethod
    def _initial(spec: SourceSpec) -> dict:
        return {"id": spec.id, "guide_id": spec.guide_id, "name": spec.name,
                "url": spec.url, "title": spec.name, "description": spec.description,
                "description_origin": "editorial", "status": "pending", "http_status": None,
                "checked_at": None, "last_success_at": None, "last_content_change_at": None,
                "content_changed": False, "error": None, "_fingerprint": None}

    def snapshot(self) -> dict:
        sources = [{key: deepcopy(value) for key, value in self._records[spec.id].items()
                    if not key.startswith("_")} for spec in self.specs]
        return {"enabled": True, "interval_hours": self.interval_seconds / 3600,
                "last_checked_at": _iso(self._last_checked) if self._last_checked else None,
                "next_check_at": _iso(self._last_started + timedelta(seconds=self.interval_seconds))
                if self._last_started else None,
                "refreshing": self._task is not None and not self._task.done(),
                "last_error": self._last_error,
                "summary": {"total": len(sources),
                            "ok": sum(s["status"] == "ok" for s in sources),
                            "unavailable": sum(s["status"] == "unavailable" for s in sources),
                            "changed": sum(s["content_changed"] for s in sources)},
                "sources": sources}

    async def refresh_if_due(self, wait: bool = False) -> dict:
        async with self._lock:
            now = self.clock()
            due = self._last_started is None or (now - self._last_started).total_seconds() >= self.interval_seconds
            if (self._task is None or self._task.done()) and due:
                self._last_started = now
                self._save_cache()
                self._task = asyncio.create_task(self._refresh())
            task = self._task
        if wait and task is not None:
            # A disconnected visitor must not cancel the shared maintenance job.
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=45.0)
            except TimeoutError:
                pass
        return self.snapshot()

    async def periodic_loop(self):
        while True:
            await self.refresh_if_due(wait=True)
            await asyncio.sleep(min(60.0, self.interval_seconds))

    async def close(self):
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _refresh(self):
        self._last_error = None
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self.request_timeout), follow_redirects=False,
                limits=httpx.Limits(max_connections=4), transport=self.transport,
                headers={"User-Agent": "QG-RENDA-SourceMonitor/1.0 (+https://qg-renda-portal-independente.onrender.com/)"},
            ) as client:
                results = await asyncio.gather(*(self._check(client, spec) for spec in self.specs))
            self._records = {record["id"]: record for record in results}
            self._last_checked = self.clock()
        except asyncio.CancelledError:
            raise
        except Exception:
            self._last_error = "refresh_failed"
            LOG.exception("Não foi possível concluir a verificação das fontes")
        finally:
            self._save_cache()

    async def _check(self, client: httpx.AsyncClient, spec: SourceSpec) -> dict:
        record = deepcopy(self._records[spec.id])
        checked = _iso(self.clock())
        record.update(checked_at=checked, content_changed=False)
        try:
            # HTTPX timeouts bound individual reads. This additional deadline
            # also bounds slow-drip responses and an entire redirect chain.
            async with asyncio.timeout(self.source_wall_timeout):
                metadata = await self._fetch(client, spec)
            fingerprint = metadata.pop("_fingerprint")
            changed = bool(record["_fingerprint"] and record["_fingerprint"] != fingerprint)
            record.update(metadata, status="ok", error=None, last_success_at=checked,
                          content_changed=changed, _fingerprint=fingerprint)
            if changed:
                record["last_content_change_at"] = checked
        except SourceFailure as exc:
            record.update(status="unavailable", http_status=exc.http_status, error=exc.code)
        except (httpx.TimeoutException, TimeoutError):
            record.update(status="unavailable", http_status=None, error="timeout")
        except httpx.HTTPError:
            record.update(status="unavailable", http_status=None, error="network_error")
        except (UnicodeError, ValueError, LookupError):
            record.update(status="unavailable", http_status=None, error="invalid_content")
        return record

    async def _fetch(self, client: httpx.AsyncClient, spec: SourceSpec) -> dict:
        url = spec.url
        for redirect in range(4):
            if not _allowed_url(url):
                raise SourceFailure("redirect_blocked")
            async with client.stream("GET", url) as response:
                status = response.status_code
                if status in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if redirect == 3 or not location:
                        raise SourceFailure("redirect_limit", status)
                    url = urljoin(url, location)
                    if not _allowed_url(url):
                        raise SourceFailure("redirect_blocked", status)
                    continue
                if status != 200:
                    raise SourceFailure(f"http_{status}", status)
                limit = MAX_PDF_BYTES if spec.kind == "pdf" else MAX_HTML_BYTES
                body = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=16384):
                    body.extend(chunk[:limit - len(body)])
                    if len(body) >= limit:
                        break
                if not body:
                    raise SourceFailure("empty_content", status)
                if spec.kind == "pdf":
                    if not bytes(body[:1024]).lstrip().startswith(b"%PDF-"):
                        raise SourceFailure("invalid_pdf", status)
                    # This fingerprint checks a bounded prefix plus HTTP metadata;
                    # it is not presented as a full-document cryptographic audit.
                    marker = "|".join([response.headers.get("etag", ""),
                                       response.headers.get("last-modified", ""),
                                       response.headers.get("content-length", ""),
                                       sha256(body).hexdigest()])
                    return {"title": spec.name, "description": spec.description,
                            "description_origin": "editorial", "http_status": status,
                            "_fingerprint": sha256(marker.encode()).hexdigest()}
                content_type = response.headers.get("content-type", "").lower()
                if content_type and "html" not in content_type:
                    raise SourceFailure("unsupported_content", status)
                parser = SourceHTML()
                parser.feed(bytes(body).decode(response.encoding or "utf-8", errors="replace"))
                if any(word in parser.title.casefold() for word in
                       ("access denied", "just a moment", "attention required", "acesso negado")):
                    raise SourceFailure("verification_blocked", status)
                if not parser.title and not parser.description and not parser.paragraph:
                    raise SourceFailure("invalid_content", status)
                description = parser.description or parser.paragraph
                title = parser.title or (parser.headings[0] if parser.headings else spec.name)
                marker = json.dumps([title, description, parser.headings], ensure_ascii=False)
                return {"title": title, "description": description or spec.description,
                        "description_origin": "source" if description else "editorial",
                        "http_status": status, "_fingerprint": sha256(marker.encode()).hexdigest()}
        raise SourceFailure("redirect_limit")

    def _load_cache(self):
        if self.cache_path is None:
            return
        try:
            if self.cache_path.stat().st_size > 128 * 1024:
                return
            cached = json.loads(self.cache_path.read_text(encoding="utf-8"))
            if cached.get("version") != 1 or not isinstance(cached.get("sources"), list):
                return
            now = self.clock()

            def past_date(value):
                parsed = _date(value)
                return parsed if parsed is not None and parsed <= now else None

            for item in cached["sources"]:
                if not isinstance(item, dict) or item.get("id") not in self._records:
                    continue
                timestamps = ("checked_at", "last_success_at", "last_content_change_at")
                if any((value := _date(item.get(key))) is not None and value > now
                       for key in timestamps):
                    continue
                if item.get("status") == "ok" and past_date(item.get("last_success_at")) is None:
                    continue
                record = self._records[item["id"]]
                for key, limit in (("title", 200), ("description", 400)):
                    if isinstance(item.get(key), str):
                        record[key] = _clean(item[key], limit)
                for key in timestamps:
                    value = past_date(item.get(key))
                    record[key] = _iso(value) if value else None
                if item.get("status") in {"pending", "ok", "unavailable"}:
                    record["status"] = item["status"]
                if item.get("description_origin") in {"source", "editorial"}:
                    record["description_origin"] = item["description_origin"]
                if isinstance(item.get("http_status"), int) and 100 <= item["http_status"] <= 599:
                    record["http_status"] = item["http_status"]
                fingerprint = item.get("_fingerprint")
                if isinstance(fingerprint, str) and re.fullmatch(r"[a-f0-9]{64}", fingerprint):
                    record["_fingerprint"] = fingerprint
                error = item.get("error")
                if isinstance(error, str) and re.fullmatch(r"[a-z0-9_]{1,50}", error):
                    record["error"] = error
                if record["status"] == "ok" and record["last_success_at"] is None:
                    record["status"] = "pending"
            self._last_started = past_date(cached.get("last_started_at"))
            self._last_checked = past_date(cached.get("last_checked_at"))
            # A process can stop after recording a start but before completing
            # the refresh. Such a start must not suppress checks after restart.
            if self._last_started is not None and (
                self._last_checked is None or self._last_checked < self._last_started
            ):
                self._last_started = None
        except (OSError, ValueError, TypeError, AttributeError):
            # Missing or corrupt cache falls back to the authored source list.
            return

    def _save_cache(self):
        if self.cache_path is None:
            return
        temporary = None
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"version": 1, "last_started_at": _iso(self._last_started)
                       if self._last_started else None,
                       "last_checked_at": _iso(self._last_checked) if self._last_checked else None,
                       "sources": list(self._records.values())}
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.cache_path.parent,
                                             prefix="sources-", suffix=".tmp", delete=False) as file:
                temporary = Path(file.name)
                json.dump(payload, file, ensure_ascii=False)
            temporary.replace(self.cache_path)
        except OSError:
            LOG.warning("Cache local indisponível; mantendo os dados em memória")
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
