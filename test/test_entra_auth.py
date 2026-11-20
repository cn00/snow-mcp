import importlib.util
import types
import unittest
from unittest.mock import Mock, patch

from servicenow_mcp_server.auth import EntraMcpConfig, EntraOnBehalfOfTokenProvider, _build_redis_storage, build_mcp_auth


class RedisStorageTests(unittest.TestCase):
    def test_default_storage_is_unchanged(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(_build_redis_storage(), (None, None))

    def test_remote_plaintext_redis_is_rejected(self):
        with patch.dict("os.environ", {"SNOW_MCP_REDIS_URL": "redis://example.com:6379"}, clear=True):
            with self.assertRaisesRegex(ValueError, "rediss"):
                _build_redis_storage()

    def test_redis_url_query_is_rejected(self):
        with patch.dict("os.environ", {"SNOW_MCP_REDIS_URL": "rediss://example.com?ssl_cert_reqs=none"}, clear=True):
            with self.assertRaisesRegex(ValueError, "SNOW_MCP_REDIS_URL"):
                _build_redis_storage()

    def test_redis_uses_encrypted_storage_and_tls_client(self):
        from cryptography.fernet import Fernet
        from key_value.aio.wrappers.encryption import FernetEncryptionWrapper
        from redis.asyncio.connection import SSLConnection

        environment = {
            "SNOW_MCP_REDIS_URL": "rediss://user:password@example.com:6379/0",
            "SNOW_MCP_REDIS_ENCRYPTION_KEY": Fernet.generate_key().decode(),
        }
        with patch.dict("os.environ", environment, clear=True):
            storage, client = _build_redis_storage()
        self.assertIs(client.connection_pool.connection_class, SSLConnection)
        self.assertIsInstance(storage, FernetEncryptionWrapper)

    def test_provider_receives_shared_storage(self):
        storage, client = object(), object()
        provider = Mock()
        azure_module = types.ModuleType("fastmcp.server.auth.providers.azure")
        azure_module.AzureProvider = provider
        environment = {
            "SNOW_ENTRA_TENANT_ID": "00000000-0000-0000-0000-000000000001",
            "SNOW_ENTRA_CLIENT_ID": "00000000-0000-0000-0000-000000000002",
            "SNOW_ENTRA_CLIENT_SECRET": "test-secret",
            "SNOW_ENTRA_MCP_SCOPE": "mcp_access",
            "SNOW_MCP_PUBLIC_BASE_URL": "https://mcp.example.com",
            "SNOW_MCP_JWT_SIGNING_KEY": "01234567890123456789012345678901",
        }
        with (
            patch.dict("os.environ", environment, clear=True),
            patch("servicenow_mcp_server.auth._build_redis_storage", return_value=(storage, client)),
            patch.dict("sys.modules", {"fastmcp.server.auth.providers.azure": azure_module}),
        ):
            result = build_mcp_auth()
        self.assertIs(provider.call_args.kwargs["client_storage"], storage)
        self.assertIs(result._snow_redis_client, client)


@unittest.skipUnless(importlib.util.find_spec("fakeredis"), "fakeredis is not installed")
class RedisSharedStorageTests(unittest.IsolatedAsyncioTestCase):
    async def test_independent_stores_share_encrypted_values(self):
        from cryptography.fernet import Fernet
        from fakeredis import FakeServer
        from fakeredis.aioredis import FakeRedis

        server = FakeServer()
        environment = {
            "SNOW_MCP_REDIS_URL": "redis://localhost:6379/0",
            "SNOW_MCP_REDIS_ENCRYPTION_KEY": Fernet.generate_key().decode(),
        }
        with (
            patch.dict("os.environ", environment, clear=True),
            patch("redis.asyncio.Redis.from_url", side_effect=lambda *args, **kwargs: FakeRedis(server=server, **kwargs)),
        ):
            first, first_client = _build_redis_storage()
            second, second_client = _build_redis_storage()
        try:
            await first.put(key="jti", value={"token": "test-upstream-token"}, collection="oauth-test")
            self.assertEqual(await second.get(key="jti", collection="oauth-test"), {"token": "test-upstream-token"})
            stored = await first_client.get((await first_client.keys())[0])
            self.assertNotIn("test-upstream-token", stored)
        finally:
            await first_client.aclose()
            await second_client.aclose()


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