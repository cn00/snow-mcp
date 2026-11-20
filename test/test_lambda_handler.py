import importlib
import json
import unittest
from unittest.mock import patch


class LambdaHandlerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        environment = {
            "SNOW_ENTRA_TENANT_ID": "00000000-0000-0000-0000-000000000001",
            "SNOW_ENTRA_CLIENT_ID": "00000000-0000-0000-0000-000000000002",
            "SNOW_ENTRA_CLIENT_SECRET": "test-secret",
            "SNOW_ENTRA_MCP_SCOPE": "mcp_access",
            "SNOW_MCP_PUBLIC_BASE_URL": "https://mcp.example.com",
            "SNOW_MCP_JWT_SIGNING_KEY": "01234567890123456789012345678901",
        }
        environment_patch = patch.dict("os.environ", environment)
        environment_patch.start()
        cls.addClassCleanup(environment_patch.stop)
        cls.lambda_module = importlib.import_module("servicenow_mcp_server.lambda_handler")
        cls.handler = staticmethod(cls.lambda_module.handler)

    def event(self, path, method="GET", body=None):
        return {
            "version": "2.0",
            "routeKey": "$default",
            "rawPath": path,
            "rawQueryString": "",
            "headers": {
                "host": "mcp.example.com",
                "accept": "application/json, text/event-stream",
                "content-type": "application/json",
            },
            "requestContext": {
                "accountId": "123456789012",
                "apiId": "example",
                "domainName": "mcp.example.com",
                "domainPrefix": "mcp",
                "http": {
                    "method": method,
                    "path": path,
                    "protocol": "HTTP/1.1",
                    "sourceIp": "127.0.0.1",
                    "userAgent": "test",
                },
                "requestId": "test-request",
                "stage": "$default",
            },
            "body": json.dumps(body) if body is not None else None,
            "isBase64Encoded": False,
        }

    def test_metadata_and_mcp_auth_across_invocations(self):
        metadata = self.handler(
            self.event("/.well-known/oauth-protected-resource/mcp"), None
        )
        self.assertEqual(metadata["statusCode"], 200)
        self.assertEqual(json.loads(metadata["body"])["resource"], "https://mcp.example.com/mcp")

        initialize = self.handler(
            self.event(
                "/mcp",
                "POST",
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-03-26",
                        "capabilities": {},
                        "clientInfo": {"name": "test", "version": "1.0"},
                    },
                },
            ),
            None,
        )
        self.assertEqual(initialize["statusCode"], 401)
        self.assertIn("www-authenticate", initialize["headers"])

    def test_authenticated_mcp_requests_across_invocations(self):
        from fastmcp.server.auth import StaticTokenVerifier

        auth = StaticTokenVerifier(tokens={"test-token": {"client_id": "test"}})
        initialize = self.event(
            "/mcp",
            "POST",
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1.0"},
                },
            },
        )
        list_tools = self.event(
            "/mcp", "POST", {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
        )
        for request in (initialize, list_tools):
            request["headers"]["authorization"] = "Bearer test-token"
            request["headers"]["mcp-protocol-version"] = "2025-03-26"

        with patch.object(self.lambda_module, "build_mcp_auth", return_value=auth):
            initialization_result = self.handler(initialize, None)
            tools_result = self.handler(list_tools, None)

        self.assertEqual(initialization_result["statusCode"], 200)
        self.assertIn("result", json.loads(initialization_result["body"]))
        self.assertEqual(tools_result["statusCode"], 200)
        self.assertTrue(json.loads(tools_result["body"])["result"]["tools"])


if __name__ == "__main__":
    unittest.main()