import importlib
import unittest


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


if __name__ == "__main__":
    unittest.main()