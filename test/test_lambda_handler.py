import importlib
import json
import os
import unittest
from unittest.mock import AsyncMock, Mock, patch


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
        cls.lambda_module = importlib.import_module("servicenow_mcp_server.lambda")
        cls.handler = staticmethod(cls.lambda_module.handler)

    def test_fastmcp_data_home_uses_lambda_writable_directory(self):
        self.assertEqual(os.environ["XDG_DATA_HOME"], "/tmp/snow-mcp")

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

    def test_redis_client_is_closed_after_invocation(self):
        from fastmcp.server.auth import StaticTokenVerifier

        auth = StaticTokenVerifier(tokens={})
        auth._snow_redis_client = Mock(aclose=AsyncMock())
        with patch.object(self.lambda_module, "build_mcp_auth", return_value=auth):
            response = self.handler(self.event("/mcp", "POST", {}), None)
        self.assertEqual(response["statusCode"], 401)
        auth._snow_redis_client.aclose.assert_awaited_once()

    def test_authenticated_prefixed_mcp_request(self):
        from fastmcp.server.auth import StaticTokenVerifier

        auth = StaticTokenVerifier(tokens={"test-token": {"client_id": "test"}})
        request = self.event(
            "/snow/mcp", "POST", {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
        )
        request["headers"]["authorization"] = "Bearer test-token"
        request["headers"]["mcp-protocol-version"] = "2025-03-26"
        with (
            patch.dict("os.environ", {"SNOW_MCP_SERVICE_PREFIX": "/snow"}),
            patch.object(self.lambda_module, "build_mcp_auth", return_value=auth),
        ):
            response = self.handler(request, None)

        self.assertEqual(response["statusCode"], 200)
        self.assertTrue(json.loads(response["body"])["result"]["tools"])

    def test_prefixed_gateway_routes_and_discovery(self):
        with patch.dict(
            "os.environ",
            {
                "SNOW_MCP_PUBLIC_BASE_URL": "https://mcp.example.com",
                "SNOW_MCP_SERVICE_PREFIX": "/snow",
            },
        ):
            metadata = self.handler(
                self.event("/.well-known/oauth-protected-resource/snow/mcp"), None
            )
            self.assertEqual(metadata["statusCode"], 200)
            resource = json.loads(metadata["body"])
            self.assertEqual(resource["resource"], "https://mcp.example.com/snow/mcp")

            authorization = self.handler(
                self.event("/.well-known/oauth-authorization-server/snow"), None
            )
            self.assertEqual(authorization["statusCode"], 200)
            authorization_metadata = json.loads(authorization["body"])
            self.assertEqual(authorization_metadata["issuer"], "https://mcp.example.com/snow")
            self.assertEqual(
                authorization_metadata["authorization_endpoint"],
                "https://mcp.example.com/snow/authorize",
            )

            for path in ("/snow/mcp", "/mcp"):
                response = self.handler(self.event(path, "POST", {}), None)
                self.assertEqual(response["statusCode"], 401)
                self.assertIn("/snow/mcp", response["headers"]["www-authenticate"])

            callback = self.handler(self.event("/snow/auth/callback"), None)
            self.assertNotEqual(callback["statusCode"], 404)

    def test_service_prefix_is_validated_and_matches_whole_segments(self):
        with patch.dict("os.environ", {"SNOW_MCP_SERVICE_PREFIX": "/snow/"}):
            self.assertEqual(self.lambda_module._api_gateway_base_path(self.event("/snow/mcp")), "/snow")
            self.assertEqual(self.lambda_module._api_gateway_base_path(self.event("/snowman/mcp")), "/")
            self.assertEqual(self.lambda_module._api_gateway_base_path(self.event("/mcp")), "/")
        for prefix in ("snow", "/snow/../other", "/snow?query=1", "/snow//other"):
            with self.subTest(prefix=prefix), patch.dict(
                "os.environ", {"SNOW_MCP_SERVICE_PREFIX": prefix}
            ):
                with self.assertRaises(ValueError):
                    self.lambda_module._api_gateway_base_path(self.event("/snow/mcp"))

    def test_standalone_prefixed_gateway_routes_and_discovery(self):
        from starlette.testclient import TestClient
        from servicenow_mcp_server.auth import build_mcp_auth
        from servicenow_mcp_server.server import create_http_app

        with patch.dict(
            "os.environ",
            {"SNOW_MCP_PUBLIC_BASE_URL": "https://mcp.example.com", "SNOW_MCP_SERVICE_PREFIX": "/snow"},
        ):
            with TestClient(create_http_app(build_mcp_auth())) as client:
                resource = client.get("/.well-known/oauth-protected-resource/snow/mcp")
                self.assertEqual(resource.status_code, 200)
                self.assertEqual(resource.json()["resource"], "https://mcp.example.com/snow/mcp")
                metadata = client.get("/.well-known/oauth-authorization-server/snow")
                self.assertEqual(metadata.status_code, 200)
                self.assertEqual(metadata.json()["issuer"], "https://mcp.example.com/snow")
                self.assertNotEqual(client.get("/snow/authorize").status_code, 404)
                self.assertNotEqual(client.get("/authorize").status_code, 404)
                for path in ("/snow/mcp", "/mcp"):
                    self.assertEqual(client.post(path, json={}).status_code, 401)
                self.assertEqual(client.post("/snowman/mcp", json={}).status_code, 404)


if __name__ == "__main__":
    unittest.main()