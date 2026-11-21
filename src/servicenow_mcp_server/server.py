# src/servicenow_mcp_server/server.py (Final Version)

import logging
import argparse
import sys
import asyncio
from urllib.parse import urlsplit
from fastmcp import FastMCP, Client
from fastmcp.tools import Tool
from starlette.routing import Route
import uvicorn
from servicenow_mcp_server.auth import build_mcp_auth, get_service_prefix

# Import all your tool registration functions
from servicenow_mcp_server.incident_management import incident_tools
from servicenow_mcp_server.table_management import table_tools
from servicenow_mcp_server.service_catalog import catalog_tools
from servicenow_mcp_server.change_management import change_tools
from servicenow_mcp_server.agile_management import story_tools, epic_tools, scrum_tools
from servicenow_mcp_server.project_management import project_tools
from servicenow_mcp_server.workflow_management import workflow_tools
from servicenow_mcp_server.script_include_management import script_include_tools
from servicenow_mcp_server.changeset_management import changeset_tools
from servicenow_mcp_server.kb_management import kb_tools
from servicenow_mcp_server.user_management import user_tools
from servicenow_mcp_server.ui_policy_management import ui_policy_tools
from servicenow_mcp_server.request_management import request_tools
from servicenow_mcp_server.analytics import analytics_tools

logging.basicConfig(level=logging.WARNING, format="[SERVER] %(message)s")

def create_mcp_instance(auth=None) -> FastMCP:
    """Creates and populates the MCP instance with all tools for the server process."""
    mcp = FastMCP(name="ServiceNow MCP Server", auth=auth)
    
    # Register tools from all modules
    incident_tools.register_tools(mcp)
    table_tools.register_tools(mcp)
    catalog_tools.register_tools(mcp)
    change_tools.register_tools(mcp)
    story_tools.register_tools(mcp)
    epic_tools.register_tools(mcp)
    scrum_tools.register_tools(mcp)
    project_tools.register_tools(mcp)
    workflow_tools.register_tools(mcp)
    script_include_tools.register_tools(mcp)
    changeset_tools.register_tools(mcp)
    kb_tools.register_tools(mcp)
    user_tools.register_tools(mcp)
    ui_policy_tools.register_tools(mcp)
    request_tools.register_tools(mcp)
    analytics_tools.register_tools(mcp)
    
    return mcp


class ServicePrefixMiddleware:
    def __init__(self, app, prefix):
        self.app = app
        self.prefix = prefix

    async def __call__(self, scope, receive, send):
        if scope["type"] in {"http", "websocket"}:
            path = scope["path"]
            if path == self.prefix or path.startswith(self.prefix + "/"):
                scope = dict(scope)
                scope["path"] = path[len(self.prefix):] or "/"
                raw_path = scope.get("raw_path")
                raw_prefix = self.prefix.encode()
                if raw_path == raw_prefix or (raw_path and raw_path.startswith(raw_prefix + b"/")):
                    scope["raw_path"] = raw_path[len(raw_prefix):] or b"/"
        await self.app(scope, receive, send)


def add_authorization_metadata_alias(app, auth):
    issuer_path = urlsplit(str(getattr(auth, "issuer_url", "") or "")).path.rstrip("/")
    metadata_path = "/.well-known/oauth-authorization-server"
    if issuer_path and not any(route.path == metadata_path + issuer_path for route in app.routes):
        for route in app.routes:
            if route.path == metadata_path:
                app.routes.append(
                    Route(metadata_path + issuer_path, endpoint=route.endpoint, methods=route.methods)
                )
                break


def create_http_app(auth):
    app = create_mcp_instance(auth=auth).http_app(transport="http")
    add_authorization_metadata_alias(app, auth)
    prefix = get_service_prefix()
    if prefix:
        app.add_middleware(ServicePrefixMiddleware, prefix=prefix)
    return app

def print_welcome_banner():
    """Prints a custom welcome banner."""
    banner = """
\033[34m 
    ███████╗███╗   ██╗ ██████╗ ██╗    ██╗      ███╗   ███╗ ██████╗██████╗
    ██╔════╝████╗  ██║██╔═══██╗██║    ██║      ████╗ ████║██╔════╝██╔══██╗
    ███████╗██╔██╗ ██║██║   ██║██║ █╗ ██║█████╗██╔████╔██║██║     ██████╔╝
    ╚════██║██║╚██╗██║██║   ██║██║███╗██║╚════╝██║╚██╔╝██║██║     ██╔═══╝
    ███████║██║ ╚████║╚██████╔╝╚███╔███╔╝      ██║ ╚═╝ ██║╚██████╗██║
    ╚══════╝╚═╝  ╚═══╝ ╚═════╝  ╚══╝╚══╝       ╚═╝     ╚═╝ ╚═════╝╚═╝
                                                                              
                🔧 ServiceNow Model Control Protocol 🔧                                                                                                                                                         
           ITSM Automation • Process Control • Data Management      
                                                                              
                [Connecting to ServiceNow Instance...]               
                                                                              \033[0m
    """
    print(banner)

def print_tool_list(all_tools: list[Tool]):
    """Prints a formatted list of all available tools."""
    print("Available Tools:")
    print("-" * 70)
    
    for tool in sorted(all_tools, key=lambda t: t.name):
        desc = (tool.description or "No description.").strip().split('\n')[0]
        print(f"  - {tool.name:<35} {desc}")
        
    print("-" * 70)
    print("For detailed parameters, please refer to the project documentation or source code.")

async def run_cli_lister():
    """
    This function acts as a temporary client to list the server's tools.
    """
    client = Client({"mcpServers": {"servicenow": {"command": "snow-mcp", "args": ["--server-mode"]}}})
    
    async with client:
        await client.ping()
        all_tools = await client.list_tools()
        print_tool_list(all_tools)

def main():
    """Main entry point for the snow-mcp command-line application."""
    parser = argparse.ArgumentParser(
        description="ServiceNow MCP Server CLI. By default, it starts the server for client connections.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    # The only CLI argument is to list tools.
    parser.add_argument('--list-tools', action='store_true', help='List all available tools and their descriptions, then exit.')
    parser.add_argument('--host', default='127.0.0.1', help='HTTP bind address.')
    parser.add_argument('--port', type=int, default=8000, help='HTTP bind port.')
    # This hidden argument prevents an infinite loop.
    parser.add_argument('--server-mode', action='store_true', help=argparse.SUPPRESS)
    
    args = parser.parse_args()
    
    if args.server_mode:
        mcp_instance = create_mcp_instance()
        mcp_instance.run(transport="stdio")
        sys.exit(0)

    if args.list_tools:
        print_welcome_banner()
        try:
            asyncio.run(run_cli_lister())
        except Exception as e:
            print(f"\nAn error occurred while inspecting the server: {e}")
        sys.exit(0)

    # --- Default behavior: A human is running 'snow-mcp' interactively, or a client is connecting ---
    if sys.stdin.isatty():
        print_welcome_banner()
        print("Starting ServiceNow MCP Server over HTTP...")
        print("Use '--list-tools' for a list of available tools.")
        print("Press Ctrl+C to exit.")
    
    app = create_http_app(auth=build_mcp_auth())
    uvicorn.run(app, host=args.host, port=args.port)

if __name__ == "__main__":
    main()