import unittest
from unittest.mock import Mock, patch

from servicenow_mcp_server.auth import EntraMcpConfig, EntraOnBehalfOfTokenProvider


class EntraMcpConfigTests(unittest.TestCase):
    def setUp(self):
        self.environment = {
            "SNOW_ENTRA_TENANT_ID": "00000000-0000-0000-0000-000000000001",
            "SNOW_ENTRA_CLIENT_ID": "00000000-0000-0000-0000-000000000002",
            "SNOW_ENTRA_CLIENT_SECRET": "test-secret",
            "SNOW_ENTRA_MCP_SCOPE": "mcp_access",
            "SNOW_MCP_PUBLIC_BASE_URL": "https://mcp.example.com/",
            "SNOW_MCP_JWT_SIGNING_KEY": "01234567890123456789012345678901",
        }

    def test_public_base_url_uses_single_configured_prefix(self):
        for prefix, expected in (
            ("", "https://mcp.example.com"),
            ("/snow/", "https://mcp.example.com/snow"),
            ("/api/snow", "https://mcp.example.com/api/snow"),
        ):
            with self.subTest(prefix=prefix), patch.dict(
                "os.environ", {**self.environment, "SNOW_MCP_SERVICE_PREFIX": prefix}, clear=True
            ):
                self.assertEqual(EntraMcpConfig.from_environment().public_base_url, expected)

    def test_public_base_url_rejects_paths(self):
        for url in ("https://mcp.example.com/snow", "https://mcp.example.com/snow/"):
            with self.subTest(url=url), patch.dict(
                "os.environ",
                {**self.environment, "SNOW_MCP_PUBLIC_BASE_URL": url, "SNOW_MCP_SERVICE_PREFIX": "/snow"},
                clear=True,
            ):
                with self.assertRaisesRegex(ValueError, "without a path"):
                    EntraMcpConfig.from_environment()

    def test_invalid_prefix_is_rejected_by_auth_configuration(self):
        with patch.dict(
            "os.environ", {**self.environment, "SNOW_MCP_SERVICE_PREFIX": "/snow/../other"}, clear=True
        ):
            with self.assertRaisesRegex(ValueError, "SNOW_MCP_SERVICE_PREFIX"):
                EntraMcpConfig.from_environment()


class EntraOnBehalfOfTokenProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_exchanges_assertion_for_configured_service_scope(self):
        client_app = Mock()
        client_app.acquire_token_on_behalf_of.return_value = {
            "access_token": "servicenow-access-token"
        }
        provider = EntraOnBehalfOfTokenProvider(
            tenant_id="tenant",
            client_id="client",
            client_secret="secret",
            service_now_scope="api://servicenow/access_as_user",
            client_app=client_app,
        )

        result = await provider("entra-user-assertion")

        self.assertEqual(result, "servicenow-access-token")
        client_app.acquire_token_on_behalf_of.assert_called_once_with(
            user_assertion="entra-user-assertion",
            scopes=["api://servicenow/access_as_user"],
        )

    async def test_does_not_return_error_payload_as_token(self):
        client_app = Mock()
        client_app.acquire_token_on_behalf_of.return_value = {
            "error": "invalid_grant",
            "error_description": "sensitive provider detail",
        }
        provider = EntraOnBehalfOfTokenProvider(
            tenant_id="tenant",
            client_id="client",
            client_secret="secret",
            service_now_scope="api://servicenow/access_as_user",
            client_app=client_app,
        )

        with self.assertRaisesRegex(RuntimeError, "could not issue"):
            await provider("entra-user-assertion")


if __name__ == "__main__":
    unittest.main()