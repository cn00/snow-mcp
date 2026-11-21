import importlib
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from fastmcp import Client


TOOL_MODULES = (
    "servicenow_mcp_server.agile_management.epic_tools",
    "servicenow_mcp_server.agile_management.scrum_tools",
    "servicenow_mcp_server.agile_management.story_tools",
    "servicenow_mcp_server.analytics.analytics_tools",
    "servicenow_mcp_server.change_management.change_tools",
    "servicenow_mcp_server.changeset_management.changeset_tools",
    "servicenow_mcp_server.incident_management.incident_tools",
    "servicenow_mcp_server.kb_management.kb_tools",
    "servicenow_mcp_server.project_management.project_tools",
    "servicenow_mcp_server.request_management.request_tools",
    "servicenow_mcp_server.script_include_management.script_include_tools",
    "servicenow_mcp_server.service_catalog.catalog_tools",
    "servicenow_mcp_server.table_management.table_tools",
    "servicenow_mcp_server.ui_policy_management.ui_policy_tools",
    "servicenow_mcp_server.user_management.user_tools",
    "servicenow_mcp_server.workflow_management.workflow_tools",
)


class ToolAuthSchemaTests(unittest.TestCase):
    def test_service_now_connection_fields_are_not_tool_inputs(self):
        for module_name in TOOL_MODULES:
            with self.subTest(module=module_name):
                params_model = importlib.import_module(module_name).BaseToolParams
                properties = params_model.model_json_schema().get("properties", {})
                self.assertTrue(
                    {"instance_url", "username", "password"}.isdisjoint(properties)
                )


class DelegatedToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_incident_tool_sends_exchanged_token(self):
        incident_tools = importlib.import_module(
            "servicenow_mcp_server.incident_management.incident_tools"
        )
        requests = []

        def handle_request(request):
            requests.append(request)
            return httpx.Response(200, json={"result": {"sys_id": "incident-id"}})

        original_client = httpx.AsyncClient
        exchange = AsyncMock(return_value="servicenow-token")
        with (
            patch.dict("os.environ", {"SERVICENOW_INSTANCE": "https://instance.service-now.com"}),
            patch("fastmcp.server.dependencies.get_access_token", return_value=SimpleNamespace(token="entra-token")),
            patch("servicenow_mcp_server.auth._service_now_token_provider", return_value=exchange),
            patch(
                "servicenow_mcp_server.utils.httpx.AsyncClient",
                side_effect=lambda **kwargs: original_client(
                    transport=httpx.MockTransport(handle_request), **kwargs
                ),
            ),
        ):
            async with Client(incident_tools.mcp) as client:
                tools = await client.list_tools()
                incident_tool = next(tool for tool in tools if tool.name == "create_incident")
                self.assertNotIn("Credentials must be provided", incident_tool.description)
                await client.call_tool("get_incident", {"params": {"sys_id": "incident-id"}})

        exchange.assert_awaited_once_with("entra-token")
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].url.host, "instance.service-now.com")
        self.assertEqual(requests[0].headers["Authorization"], "Bearer servicenow-token")


if __name__ == "__main__":
    unittest.main()