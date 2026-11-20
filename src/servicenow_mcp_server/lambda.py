"""AWS Lambda adapter for the authenticated Streamable HTTP MCP server."""

import os
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

os.environ["XDG_DATA_HOME"] = "/tmp/snow-mcp"

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
    redis_client = getattr(auth, "_snow_redis_client", None)
    if redis_client is not None:
        original_lifespan = app.router.lifespan_context

        @asynccontextmanager
        async def lifespan(application):
            try:
                async with original_lifespan(application) as state:
                    yield state
            finally:
                await redis_client.aclose()

        app.router.lifespan_context = lifespan
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