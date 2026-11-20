import unittest
from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()