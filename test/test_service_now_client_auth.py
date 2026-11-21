import unittest
from unittest.mock import AsyncMock, Mock, patch

import httpx

from servicenow_mcp_server.utils import ServiceNowClient


class FakeAsyncClient:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    async def aclose(self):
        pass


class ServiceNowClientAuthTests(unittest.IsolatedAsyncioTestCase):
    async def test_token_provider_sets_bearer_header_and_verifies_tls(self):
        async def token_provider():
            return "delegated-access-token"

        with patch(
            "servicenow_mcp_server.utils.httpx.AsyncClient", FakeAsyncClient
        ):
            async with ServiceNowClient(
                "https://instance.service-now.com", token_provider=token_provider
            ) as client:
                self.assertEqual(
                    client._client.kwargs["headers"]["Authorization"],
                    "Bearer delegated-access-token",
                )
                self.assertIs(client._client.kwargs["verify"], True)

    def test_rejects_basic_credentials(self):
        with self.assertRaisesRegex(ValueError, "Basic authentication is no longer supported"):
            ServiceNowClient(
                "https://instance.service-now.com",
                username="user",
                password="password",
            )

    def test_rejects_unsafe_instance_urls(self):
        for instance_url in (
            "http://instance.service-now.com",
            "https://user:password@instance.service-now.com",
            "https://instance.service-now.com?token=secret",
            "https://instance.service-now.com#fragment",
        ):
            with self.subTest(instance_url=instance_url):
                with self.assertRaises(ValueError):
                    ServiceNowClient(instance_url)

    async def test_debug_logs_api_and_status_without_sensitive_values(self):
        for raw in (False, True):
            with self.subTest(raw=raw):
                response = httpx.Response(
                    200, json={"result": []}, request=httpx.Request("POST", "https://instance.service-now.com/api/now/table/incident")
                )
                client = ServiceNowClient("https://instance.service-now.com")
                client._client = Mock(request=AsyncMock(return_value=response))
                with self.assertLogs("servicenow_mcp_server.utils", level="DEBUG") as captured:
                    if raw:
                        await client.send_raw_request(
                            "POST", "/api/now/table/incident?token=query-secret",
                            params={"password": "param-secret"}, data=b"body-secret",
                            headers={"Authorization": "Bearer header-secret"},
                        )
                    else:
                        await client.send_request(
                            "POST", "/api/now/table/incident?token=query-secret",
                            params={"password": "param-secret"}, data={"secret": "body-secret"},
                        )
                output = "\n".join(captured.output)
                self.assertIn("POST /api/now/table/incident", output)
                self.assertIn("status=200", output)
                for secret in ("query-secret", "param-secret", "body-secret", "header-secret", "Authorization"):
                    self.assertNotIn(secret, output)

    async def test_debug_logs_network_error_type_without_details(self):
        client = ServiceNowClient("https://instance.service-now.com")
        client._client = Mock(request=AsyncMock(side_effect=httpx.ConnectError("sensitive-detail")))
        with self.assertLogs("servicenow_mcp_server.utils", level="DEBUG") as captured:
            await client.send_request("GET", "/api/now/table/incident")
        output = "\n".join(captured.output)
        self.assertIn("ConnectError", output)
        self.assertNotIn("sensitive-detail", output)

    async def test_debug_logs_http_error_status_without_response_body(self):
        response = httpx.Response(
            403, text="sensitive-response", request=httpx.Request("GET", "https://instance.service-now.com/api/now/table/incident")
        )
        client = ServiceNowClient("https://instance.service-now.com")
        client._client = Mock(request=AsyncMock(return_value=response))
        with self.assertLogs("servicenow_mcp_server.utils", level="DEBUG") as captured:
            result = await client.send_request("GET", "/api/now/table/incident")
        self.assertEqual(result["status_code"], 403)
        output = "\n".join(captured.output)
        self.assertIn("status=403", output)
        self.assertNotIn("sensitive-response", output)


if __name__ == "__main__":
    unittest.main()