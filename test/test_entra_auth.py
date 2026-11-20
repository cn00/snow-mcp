import unittest
from unittest.mock import Mock

from servicenow_mcp_server.auth import EntraOnBehalfOfTokenProvider


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