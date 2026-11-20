"""AWS Lambda adapter for the authenticated Streamable HTTP MCP server."""

from mangum import Mangum

from servicenow_mcp_server.auth import build_mcp_auth
from servicenow_mcp_server.server import create_mcp_instance


def handler(event, context):
    app = create_mcp_instance(auth=build_mcp_auth()).http_app(
        transport="http", stateless_http=True, json_response=True
    )
    return Mangum(app, lifespan="auto")(event, context)