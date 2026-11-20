# AWS Lambda entry point

The Lambda handler is `servicenow_mcp_server.lambda.handler`. Package the project and its dependencies, including Mangum, in the Lambda deployment artifact. Configure the Entra and ServiceNow environment variables described in [entra-sso.md](entra-sso.md).

## Build ZIPs in WSL

Install the project and its dependencies into the workspace `.venv` first, then run:

```bash
./.venv/bin/python -m pip install -e .
bash scripts/wsl-dev.sh lambda-package
```

The script writes `.artifacts/lambda-src.zip` with `servicenow_mcp_server/` at its root, and `.artifacts/lambda-layer.zip` with dependencies under `python/lib/pythonX.Y/site-packages/`. The project editable-install link and metadata are excluded from the layer. The Python version is taken from `.venv`; its Linux runtime, native libraries and CPU architecture must match the target Lambda environment.

Use `lambda-src` or `lambda-layer` instead of `lambda-package` to build only one ZIP. Set `LAMBDA_ARTIFACT_DIR` to change the output directory. Existing ZIPs are never overwritten; move them or select another directory before rebuilding. AWS Lambda package and layer size limits still apply.

## Simulate API Gateway locally

With AWS SAM CLI and Docker installed, build `.artifacts/lambda-layer.zip` if it does not already exist:

```bash
bash scripts/wsl-dev.sh lambda-layer
NO_PROXY="${NO_PROXY:+$NO_PROXY,}localhost,127.0.0.1,::1" \
no_proxy="${no_proxy:+$no_proxy,}localhost,127.0.0.1,::1" \
sam local start-api --template-file template.local.yaml --port 3000 --warm-containers LAZY
```

SAM starts its own Lambda container; it does not forward to the container in `docker-compose.yaml`. The loopback proxy bypass prevents SAM's requests to the local Lambda container from being sent through an HTTP proxy. The template uses the current `src/` directory, the dependency layer ZIP, and HTTP API payload format 2.0. Its Entra values are nonfunctional local placeholders, not real credentials. It advertises `http://localhost:3000` with the `/snow-mcp` prefix, so discovery and unauthenticated MCP requests can be tested directly:

```bash
curl --noproxy '*' -i http://localhost:3000/.well-known/oauth-protected-resource/snow-mcp/mcp
curl --noproxy '*' -i http://localhost:3000/.well-known/oauth-authorization-server/snow-mcp
curl --noproxy '*' -i -X POST http://localhost:3000/snow-mcp/mcp \
	-H 'Content-Type: application/json' \
	-H 'Accept: application/json, text/event-stream' \
	-d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"local-test","version":"1.0"}}}'
```

Discovery should return HTTP 200; the MCP request should return HTTP 401 without a bearer token. For real sign-in, supply a private SAM `--env-vars` JSON file keyed by `LocalMcpFunction` with the required settings from [entra-sso.md](entra-sso.md), including the matching public origin and service prefix. Do not commit credentials. Entra redirect URI and HTTPS requirements still apply, and a local test does not replace the shared OAuth storage required in production.

Use an API Gateway HTTP API with Lambda proxy integration and payload format 2.0. Route `/mcp`, the OAuth endpoints, and the `/.well-known` discovery endpoints to the handler. `SNOW_MCP_PUBLIC_BASE_URL` must match the externally reachable HTTPS origin without a path. Configure an exact Entra web redirect URI for the resulting `/auth/callback` endpoint.

For a public service prefix, set both values, for example:

```bash
SNOW_MCP_PUBLIC_BASE_URL=https://mcp.example.com
SNOW_MCP_SERVICE_PREFIX=/snow
```

The public MCP endpoint is `https://mcp.example.com/snow/mcp` and the Entra redirect URI is `https://mcp.example.com/snow/auth/callback`. The service prefix is appended to the public base URL when constructing advertised OAuth URLs. It also tells the Lambda adapter to remove `/snow` when the gateway includes it. If the gateway has already stripped the prefix, the adapter accepts `/mcp` and `/auth/callback` unchanged. If the service prefix is unset, URLs and routes remain at the root. When upgrading an existing deployment, remove any path from `SNOW_MCP_PUBLIC_BASE_URL` and put it in `SNOW_MCP_SERVICE_PREFIX`; otherwise the base URL is rejected.

The gateway must also forward the root-level path-aware OAuth discovery endpoints `/.well-known/oauth-protected-resource/snow/mcp` and `/.well-known/oauth-authorization-server/snow` to the same Lambda. Do not put `/snow` before `/.well-known`; discovery paths are rooted at the domain. Ensure `/snow/authorize`, `/snow/token`, `/snow/register`, and `/snow/auth/callback` also reach the Lambda, with the appropriate HTTP methods. If API Gateway uses a custom-domain API mapping, verify explicitly which prefixes are retained in its Lambda event and that the root-level discovery routes reach this integration.

The adapter creates a stateless Streamable HTTP app with JSON responses for each invocation. Mangum and API Gateway proxy responses are buffered; long-lived server-sent event streams are not supported by this entry point.

## OAuth storage limitation

The existing FastMCP OAuth proxy uses local persistent state for client registrations, authorization transactions, and upstream tokens. Lambda execution environments have isolated ephemeral filesystems, and their default home directory may not be writable. Merely configuring a writable temporary directory does not share state across environments or preserve it across cold starts.

Consequently, dynamic registration, OAuth callbacks, token refresh, and authenticated MCP calls are **not production-ready on Lambda** until the OAuth provider is configured with a shared persistent store, encryption at rest, and stable signing and encryption keys. The current `build_mcp_auth()` does not configure such a shared store. Alternatively, deploy the existing server on a suitable long-running host. Protect secrets using an AWS-managed secret store and never log tokens.

## Validation

Run the local API Gateway event tests with:

```bash
python -m unittest discover -s test -p 'test_lambda_handler.py' -v
```

These tests verify repeated invocations, OAuth metadata, and MCP authentication with a test verifier. They do not prove Entra sign-in, ServiceNow OBO, shared OAuth storage, or deployed API Gateway behavior. Validate those flows in the target AWS environment before use.