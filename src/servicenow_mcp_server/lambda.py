"""AWS Lambda adapter for the authenticated Streamable HTTP MCP server."""

from urllib.parse import urlsplit

from mangum import Mangum
from starlette.routing import Route

from servicenow_mcp_server.auth import build_mcp_auth, get_service_prefix
from servicenow_mcp_server.server import create_mcp_instance


def _api_gateway_base_path(event):
    prefix = get_service_prefix()
    if not prefix:
        return "/"

    path = event.get("rawPath") or event.get("path") or ""
    if path == prefix or path.startswith(prefix + "/"):
        return prefix
    return "/"


def handler(event, context):
    base_path = _api_gateway_base_path(event)
    auth = build_mcp_auth()
    app = create_mcp_instance(auth=auth).http_app(
        transport="http", stateless_http=True, json_response=True
    )
    issuer_path = urlsplit(str(getattr(auth, "issuer_url", "") or "")).path.rstrip("/")
    metadata_path = "/.well-known/oauth-authorization-server"
    if issuer_path and not any(route.path == metadata_path + issuer_path for route in app.routes):
        for route in app.routes:
            if route.path == metadata_path:
                app.routes.append(
                    Route(metadata_path + issuer_path, endpoint=route.endpoint, methods=route.methods)
                )
                break
    return Mangum(app, lifespan="auto", api_gateway_base_path=base_path)(event, context)