import importlib.util
import json
import types
import unittest
from unittest.mock import Mock, patch

from servicenow_mcp_server.auth import EntraMcpConfig, EntraOnBehalfOfTokenProvider, _build_redis_storage, _service_now_token_provider, build_mcp_auth


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

    async def test_saml_mode_requests_a_saml2_assertion(self):
        client_app = Mock()
        client_app.acquire_token_on_behalf_of.return_value = {
            "access_token": "c2FtbC1hc3NlcnRpb24",
            "token_type": "Bearer",
            "issued_token_type": "urn:ietf:params:oauth:token-type:saml2",
        }
        provider = EntraOnBehalfOfTokenProvider(
            "tenant", "client", "secret", "https://saml.example.com/.default", client_app, auth_mode="saml"
        )
        self.assertEqual(await provider("entra-user-assertion"), "c2FtbC1hc3NlcnRpb24")
        client_app.acquire_token_on_behalf_of.assert_called_once_with(
            user_assertion="entra-user-assertion",
            scopes=["https://saml.example.com/.default"],
            data={"requested_token_type": "urn:ietf:params:oauth:token-type:saml2"},
        )

    async def test_saml_mode_rejects_unexpected_or_unsafe_tokens(self):
        for token, token_type, issued_type in (
            ("jwt-token", "Bearer", "urn:ietf:params:oauth:token-type:access_token"),
            ("saml-token", "Bearer", None),
            ("saml-token", "Other", "urn:ietf:params:oauth:token-type:saml2"),
            ("saml-token\r\nInjected: value", "Bearer", "urn:ietf:params:oauth:token-type:saml2"),
        ):
            with self.subTest(token_type=token_type, issued_type=issued_type):
                client_app = Mock()
                client_app.acquire_token_on_behalf_of.return_value = {
                    "access_token": token, "token_type": token_type, "issued_token_type": issued_type,
                }
                provider = EntraOnBehalfOfTokenProvider(
                    "tenant", "client", "secret", "https://saml.example.com/.default", client_app, auth_mode="saml"
                )
                with self.assertRaisesRegex(RuntimeError, "valid SAML 2.0 bearer assertion"):
                    await provider("entra-user-assertion")

    def test_auth_mode_and_saml_scope_are_validated(self):
        with self.assertRaisesRegex(ValueError, "SERVICENOW_AUTH_MODE"):
            EntraOnBehalfOfTokenProvider("tenant", "client", "secret", "scope", Mock(), auth_mode="other")
        for scope in ("https://saml.example.com/user_impersonation", "/.default", "https://saml.example.com/.default other"):
            with self.subTest(scope=scope), self.assertRaises(ValueError):
                EntraOnBehalfOfTokenProvider("tenant", "client", "secret", scope, Mock(), auth_mode="saml")

    def test_saml_msal_client_excludes_optional_oidc_scopes(self):
        with patch("msal.ConfidentialClientApplication") as client_app:
            EntraOnBehalfOfTokenProvider("tenant", "client", "secret", "https://saml.example.com/.default", auth_mode="saml")
        self.assertEqual(client_app.call_args.kwargs["exclude_scopes"], ["profile", "offline_access"])

    async def test_saml_parameters_are_forwarded_by_msal(self):
        from msal import ConfidentialClientApplication
        from msal.oauth2cli.oauth2 import Client

        response = {
            "access_token": "c2FtbC1hc3NlcnRpb24",
            "token_type": "Bearer",
            "issued_token_type": "urn:ietf:params:oauth:token-type:saml2",
        }
        http_client = Mock()
        http_client.post.return_value = Mock(status_code=200, text=json.dumps(response))
        client_app = object.__new__(ConfidentialClientApplication)
        client_app.client = Client(
            {"token_endpoint": "https://login.example.com/tenant/oauth2/v2.0/token"},
            "client", http_client=http_client, client_secret="secret",
        )
        client_app._exclude_scopes = frozenset({"profile", "offline_access"})
        client_app._client_capabilities = None
        client_app._build_telemetry_context = Mock()
        client_app._build_telemetry_context.return_value.generate_headers.return_value = {}
        provider = EntraOnBehalfOfTokenProvider(
            "tenant", "client", "secret", "https://saml.example.com/.default", client_app, auth_mode="saml"
        )
        self.assertEqual(await provider("entra-user-assertion"), "c2FtbC1hc3NlcnRpb24")
        body = http_client.post.call_args.kwargs["data"]
        self.assertEqual(body["requested_token_type"], "urn:ietf:params:oauth:token-type:saml2")
        self.assertEqual(body["requested_token_use"], "on_behalf_of")
        self.assertEqual(body["grant_type"], "urn:ietf:params:oauth:grant-type:jwt-bearer")
        self.assertEqual(body["assertion"], "entra-user-assertion")
        self.assertEqual(set(body["scope"].split()), {"openid", "https://saml.example.com/.default"})

    def test_environment_selects_saml_mode(self):
        environment = {
            "SNOW_ENTRA_TENANT_ID": "00000000-0000-0000-0000-000000000001",
            "SNOW_ENTRA_CLIENT_ID": "00000000-0000-0000-0000-000000000002",
            "SNOW_ENTRA_CLIENT_SECRET": "secret",
            "SERVICENOW_OBO_SCOPE": "https://saml.example.com/.default",
            "SERVICENOW_AUTH_MODE": "saml",
        }
        _service_now_token_provider.cache_clear()
        self.addCleanup(_service_now_token_provider.cache_clear)
        with patch.dict("os.environ", environment, clear=True), patch("servicenow_mcp_server.auth.EntraOnBehalfOfTokenProvider") as provider:
            _service_now_token_provider()
        self.assertEqual(provider.call_args.kwargs["auth_mode"], "saml")
        self.assertEqual(provider.call_args.kwargs["service_now_scope"], environment["SERVICENOW_OBO_SCOPE"])

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

    async def test_failed_exchange_logs_only_safe_entra_diagnostics(self):
        client_app = Mock()
        client_app.acquire_token_on_behalf_of.return_value = {
            "error": "invalid_grant",
            "error_codes": [65001],
            "error_description": "AADSTS65001 sensitive-provider-detail",
            "trace_id": "11111111-1111-1111-1111-111111111111",
            "correlation_id": "22222222-2222-2222-2222-222222222222",
            "access_token": "",
        }
        provider = EntraOnBehalfOfTokenProvider("tenant", "client", "client-secret", "api://servicenow/access", client_app)
        with self.assertLogs("servicenow_mcp_server.auth", level="WARNING") as captured:
            with self.assertRaisesRegex(RuntimeError, "could not issue"):
                await provider("user-assertion-secret")
        output = "\n".join(captured.output)
        for expected in ("invalid_grant", "65001", "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"):
            self.assertIn(expected, output)
        for sensitive in ("sensitive-provider-detail", "client-secret", "user-assertion-secret"):
            self.assertNotIn(sensitive, output)

    async def test_failed_exchange_rejects_untrusted_diagnostic_values(self):
        client_app = Mock()
        client_app.acquire_token_on_behalf_of.return_value = {
            "error": "secret-token",
            "error_codes": [True, "secret-code", -1, 999999999],
            "error_description": "AADSTS7000215 secret-description",
            "trace_id": "secret-trace",
            "correlation_id": "secret-correlation",
        }
        provider = EntraOnBehalfOfTokenProvider("tenant", "client", "secret", "api://servicenow/access", client_app)
        with self.assertLogs("servicenow_mcp_server.auth", level="WARNING") as captured:
            with self.assertRaisesRegex(RuntimeError, "could not issue"):
                await provider("assertion")
        output = "\n".join(captured.output)
        self.assertIn("error=unknown", output)
        self.assertIn("7000215", output)
        self.assertIn("trace_id=unavailable", output)
        for sensitive in ("secret-token", "secret-code", "secret-description", "secret-trace", "secret-correlation"):
            self.assertNotIn(sensitive, output)


if __name__ == "__main__":
    unittest.main()