"""Maintenance tests use mocked HTTP only; no public source is contacted."""
import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import httpx

from portal_automation import AutomationManager, SourceSpec, DEFAULT_SOURCES


def source(kind="html"):
    return SourceSpec("fonte", "guia-fontes", "Fonte editorial",
                      "https://www.gov.br/teste", "Referência editorial confirmada.", kind)


def html(title="Título da fonte", description="Descrição publicada pela fonte."):
    return f'<html><head><title>{title}</title><meta name="description" content="{description}"></head><body><main><h1>Orientações públicas</h1></main></body></html>'


def response(*args, **kwargs):
    # Mock fixtures explicitly carry the MIME that an HTML server sends.
    if kwargs.get("text", "").lstrip().startswith("<html>"):
        headers = dict(kwargs.get("headers", {}))
        headers.setdefault("content-type", "text/html; charset=utf-8")
        kwargs["headers"] = headers
    return httpx.Response(*args, **kwargs)


class MutableClock:
    def __init__(self):
        self.now = datetime(2026, 11, 14, 12, tzinfo=timezone.utc)

    def __call__(self):
        return self.now

    def advance(self, seconds=21600):
        self.now += timedelta(seconds=seconds)


class AutomationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.clock = MutableClock()
        self.managers = []

    async def asyncTearDown(self):
        for manager in self.managers:
            await manager.close()

    def manager(self, handler, **kwargs):
        manager = AutomationManager(specs=(source(),), cache_path=None,
                                    clock=self.clock, transport=httpx.MockTransport(handler), **kwargs)
        self.managers.append(manager)
        return manager

    async def test_source_metadata_is_extracted_and_internal_fingerprint_not_public(self):
        manager = self.manager(lambda req: response(200, text=html()))
        payload = await manager.refresh_if_due(wait=True)
        record = payload["sources"][0]
        self.assertEqual(record["status"], "ok")
        self.assertEqual(record["title"], "Título da fonte")
        self.assertEqual(record["description"], "Descrição publicada pela fonte.")
        self.assertEqual(record["description_origin"], "source")
        self.assertEqual(record["url"], "https://www.gov.br/teste")
        self.assertEqual(payload["summary"], {"total": 1, "ok": 1, "unavailable": 0, "changed": 0})
        self.assertFalse(payload["refreshing"])
        self.assertIsNone(record["last_content_change_at"])
        self.assertFalse(any(key.startswith("_") for key in record))

    async def test_concurrent_visitors_share_one_refresh_and_ttl_prevents_storm(self):
        calls = []

        async def handle(req):
            calls.append(str(req.url))
            await asyncio.sleep(.01)
            return response(200, text=html())

        manager = self.manager(handle)
        results = await asyncio.gather(*(manager.refresh_if_due(wait=True) for _ in range(20)))
        self.assertEqual(len(calls), 1)
        self.assertTrue(all(result["last_checked_at"] for result in results))
        self.clock.advance(21599)
        await manager.refresh_if_due(wait=True)
        self.assertEqual(len(calls), 1)
        self.clock.advance(2)
        await manager.refresh_if_due(wait=True)
        self.assertEqual(len(calls), 2)

    async def test_metadata_changes_are_detected_without_bumping_unchanged_content_date(self):
        version = ["Primeira descrição."]
        manager = self.manager(lambda req: response(200, text=html(description=version[0])))
        await manager.refresh_if_due(wait=True)
        version[0] = "Nova descrição publicada."
        self.clock.advance()
        changed = await manager.refresh_if_due(wait=True)
        record = changed["sources"][0]
        self.assertEqual(record["description"], version[0])
        self.assertEqual(changed["summary"]["changed"], 1)
        change_date = record["last_content_change_at"]
        self.assertIsNotNone(change_date)
        self.clock.advance()
        unchanged = await manager.refresh_if_due(wait=True)
        self.assertEqual(unchanged["summary"]["changed"], 0)
        self.assertEqual(unchanged["sources"][0]["last_content_change_at"], change_date)

    async def test_timeout_preserves_last_known_content_and_success_date(self):
        fail = [False]

        def handle(req):
            if fail[0]:
                raise httpx.ReadTimeout("not exposed", request=req)
            return response(200, text=html())

        manager = self.manager(handle)
        good = (await manager.refresh_if_due(wait=True))["sources"][0]
        self.assertEqual(good["status"], "ok")
        fail[0] = True
        self.clock.advance()
        payload = await manager.refresh_if_due(wait=True)
        failed = payload["sources"][0]
        self.assertEqual(failed["status"], "unavailable")
        self.assertEqual(failed["error"], "timeout")
        self.assertEqual(failed["description"], good["description"])
        self.assertEqual(failed["title"], good["title"])
        self.assertEqual(failed["last_success_at"], good["last_success_at"])
        self.assertNotEqual(failed["checked_at"], good["checked_at"])
        self.assertEqual(payload["summary"]["unavailable"], 1)
        self.assertIsNone(payload["last_error"])

    async def test_not_found_and_challenge_page_are_not_published_as_new_guidance(self):
        responses = [response(200, text=html())]
        manager = self.manager(lambda req: responses[0])
        good = (await manager.refresh_if_due(wait=True))["sources"][0]
        self.assertEqual(good["status"], "ok")
        for bad in (response(404, text="missing"),
                    response(200, text=html("Access Denied", "Blocked response"))):
            responses[0] = bad
            self.clock.advance()
            failed = (await manager.refresh_if_due(wait=True))["sources"][0]
            self.assertEqual(failed["status"], "unavailable")
            self.assertEqual(failed["description"], good["description"])

    async def test_redirect_to_private_or_unapproved_host_is_never_requested(self):
        for destination in ("http://127.0.0.1/secret", "https://example.com/", "https://www.gov.br:444/teste"):
            calls = []

            def handle(req):
                calls.append(str(req.url))
                return response(302, headers={"location": destination})

            manager = self.manager(handle)
            record = (await manager.refresh_if_due(wait=True))["sources"][0]
            self.assertEqual(record["error"], "redirect_blocked")
            self.assertEqual(calls, ["https://www.gov.br/teste"])

    async def test_redirect_within_approved_hosts_is_followed_but_curated_link_stays_fixed(self):
        calls = []

        def handle(req):
            calls.append(str(req.url))
            if req.url.path == "/teste":
                return response(301, headers={"location": "/nova-pagina"})
            return response(200, text=html())

        manager = self.manager(handle)
        record = (await manager.refresh_if_due(wait=True))["sources"][0]
        self.assertEqual(record["status"], "ok")
        self.assertEqual(record["url"], "https://www.gov.br/teste")
        self.assertEqual(len(calls), 2)

    async def test_slow_drip_is_bounded_by_total_source_deadline(self):
        reads = []

        class SlowBody(httpx.AsyncByteStream):
            async def __aiter__(self):
                for _ in range(100):
                    await asyncio.sleep(.01)
                    reads.append(1)
                    yield b" " * 16384

        manager = self.manager(lambda req: response(200, stream=SlowBody()), source_wall_timeout=.035)
        started = time.monotonic()
        record = (await manager.refresh_if_due(wait=True))["sources"][0]
        self.assertLess(time.monotonic() - started, .5)
        self.assertEqual(record["error"], "timeout")
        self.assertLess(len(reads), 10)

    async def test_pdf_is_read_with_a_bound_and_description_is_editorial(self):
        reads = []

        class PDFBody(httpx.AsyncByteStream):
            async def __aiter__(self):
                for index in range(1000):
                    reads.append(index)
                    yield (b"%PDF-1.7\n" + b"x" * 16375) if index == 0 else b"x" * 16384

        manager = AutomationManager(specs=(source("pdf"),), cache_path=None, clock=self.clock,
            transport=httpx.MockTransport(lambda req: response(200, stream=PDFBody(), headers={"content-type": "application/pdf"})))
        self.managers.append(manager)
        record = (await manager.refresh_if_due(wait=True))["sources"][0]
        self.assertEqual(record["status"], "ok")
        self.assertEqual(record["description_origin"], "editorial")
        self.assertEqual(record["description"], source("pdf").description)
        self.assertLessEqual(len(reads), 5)

    async def test_valid_cache_survives_reload_without_accepting_cached_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sources.json"
            calls = []

            def handle(req):
                calls.append(str(req.url))
                return response(200, text=html())

            manager = AutomationManager((source(),), path, httpx.MockTransport(handle), self.clock)
            self.managers.append(manager)
            good = await manager.refresh_if_due(wait=True)
            cached = json.loads(path.read_text())
            cached["sources"][0]["url"] = "http://127.0.0.1/"
            path.write_text(json.dumps(cached))
            restored = AutomationManager((source(),), path, httpx.MockTransport(handle), self.clock)
            self.managers.append(restored)
            payload = await restored.refresh_if_due(wait=True)
            self.assertEqual(len(calls), 1)
            self.assertEqual(payload["sources"][0]["description"], good["sources"][0]["description"])
            self.assertEqual(payload["sources"][0]["url"], source().url)

    async def test_corrupt_cache_falls_back_and_checks_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sources.json"
            for invalid in ("{", "[]", '{"version":999,"sources":[]}'):
                path.write_text(invalid)
                manager = AutomationManager((source(),), path, httpx.MockTransport(lambda req: response(200, text=html())), self.clock)
                self.managers.append(manager)
                self.assertEqual(manager.snapshot()["sources"][0]["status"], "pending")
                self.assertEqual((await manager.refresh_if_due(wait=True))["sources"][0]["status"], "ok")

    async def test_interrupted_or_future_cache_does_not_suppress_refresh(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sources.json"
            now = self.clock().isoformat()
            past = (self.clock() - timedelta(hours=6)).isoformat()
            future = (self.clock() + timedelta(days=3)).isoformat()
            for started, checked in ((now, None), (now, past), (future, future)):
                path.write_text(json.dumps({"version": 1, "last_started_at": started,
                                            "last_checked_at": checked, "sources": []}))
                calls = []

                def handle(req):
                    calls.append(str(req.url))
                    return response(200, text=html())

                manager = AutomationManager((source(),), path, httpx.MockTransport(handle), self.clock)
                self.managers.append(manager)
                payload = await manager.refresh_if_due(wait=True)
                self.assertEqual(len(calls), 1)
                self.assertFalse(payload["refreshing"])
                self.assertIsNotNone(payload["last_checked_at"])

    async def test_cache_cleanup_failure_does_not_break_refresh(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sources.json"
            manager = AutomationManager((source(),), path, httpx.MockTransport(lambda req: response(200, text=html())), self.clock)
            self.managers.append(manager)
            with patch.object(Path, "unlink", side_effect=PermissionError("cleanup unavailable")):
                result = await manager.refresh_if_due(wait=True)
            self.assertEqual(result["sources"][0]["status"], "ok")
            self.assertTrue(path.exists())

    async def test_future_source_record_is_rejected_in_favor_of_authored_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sources.json"
            future = (self.clock() + timedelta(days=3)).isoformat()
            path.write_text(json.dumps({"version": 1, "sources": [{
                "id": "fonte", "status": "ok", "title": "Unverified future content",
                "description": "Must not replace the authored fallback",
                "description_origin": "source", "last_success_at": future,
            }]}))
            manager = AutomationManager((source(),), path, httpx.MockTransport(lambda req: response(200, text=html())), self.clock)
            self.managers.append(manager)
            pending = manager.snapshot()["sources"][0]
            self.assertEqual(pending["status"], "pending")
            self.assertEqual(pending["description"], source().description)
            self.assertIsNone(pending["last_success_at"])
            self.assertEqual((await manager.refresh_if_due(wait=True))["sources"][0]["status"], "ok")

    async def test_invalid_source_configuration_is_rejected(self):
        for url in ("http://www.gov.br/", "https://evil.example/", "https://user@www.gov.br/", "https://www.gov.br:444/"):
            with self.assertRaises(ValueError):
                SourceSpec("invalid", None, "Invalid", url, "Invalid")
        self.assertEqual(len(DEFAULT_SOURCES), 7)


if __name__ == "__main__":
    unittest.main()
