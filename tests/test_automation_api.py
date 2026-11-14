"""API integration without outbound network or visitor conversations."""
import asyncio
import unittest

import httpx
from fastapi.testclient import TestClient

from portal_automation import AutomationManager, SourceSpec
from portal_institucional import create_app


class AutomationApiTests(unittest.TestCase):
    def make_manager(self, handler):
        return AutomationManager(
            specs=(SourceSpec("servicos", "guia-fontes", "Serviços", "https://www.gov.br/pt-br/servicos", "Referência editorial"),),
            cache_path=None, transport=httpx.MockTransport(handler),
        )

    def test_waiting_api_uses_fixed_sources_and_no_conversation_endpoint(self):
        requests = []

        async def handler(request):
            requests.append(str(request.url))
            return httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"},
                                  text='<title>Serviços públicos</title><meta name="description" content="Informações da fonte">')

        manager = self.make_manager(handler)
        with TestClient(create_app(lambda: manager)) as client:
            response = client.get("/api/automation?wait=true&url=https://127.0.0.1/private")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["cache-control"], "no-store")
            data = response.json()
            self.assertTrue(data["enabled"])
            self.assertFalse(data["refreshing"])
            self.assertEqual(data["summary"]["ok"], 1)
            self.assertEqual(data["sources"][0]["title"], "Serviços públicos")
            self.assertEqual(client.post("/api/automation", json={"question": "dúvida"}).status_code, 405)
        self.assertEqual(requests, ["https://www.gov.br/pt-br/servicos"])

    def test_upstream_wait_does_not_block_site_readiness(self):
        async def handler(_request):
            await asyncio.Event().wait()

        manager = self.make_manager(handler)
        with TestClient(create_app(lambda: manager)) as client:
            response = client.get("/health")
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()["ok"])
            self.assertFalse(response.json()["personal_data_collection_enabled"])
            self.assertEqual(client.get("/").status_code, 200)


if __name__ == "__main__":
    unittest.main()
