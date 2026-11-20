# AWS Lambda entry point

The Lambda handler is `servicenow_mcp_server.lambda.handler`. Package the project and its dependencies, including Mangum, in the Lambda deployment artifact. Configure the Entra and ServiceNow environment variables described in [entra-sso.md](entra-sso.md).

## Build ZIPs in WSL

Install the project and its dependencies into the workspace `.venv` first, then run:

```bash
./.venv/bin/python -m pip install -e .
bash scripts/wsl-dev.sh lambda-package
```

The script writes `.artifacts/lambda/lambda-src.zip` with `servicenow_mcp_server/` at its root, and `.artifacts/lambda/lambda-layer.zip` with dependencies under `python/lib/pythonX.Y/site-packages/`. The project editable-install link and metadata are excluded from the layer. The Python version is taken from `.venv`; its Linux runtime, native libraries and CPU architecture must match the target Lambda environment.

Use `lambda-src` or `lambda-layer` instead of `lambda-package` to build only one ZIP. Set `LAMBDA_ARTIFACT_DIR` to change the output directory. Existing ZIPs are never overwritten; move them or select another directory before rebuilding. AWS Lambda package and layer size limits still apply.

Use an API Gateway HTTP API with Lambda proxy integration and payload format 2.0. Route `/mcp`, the OAuth endpoints, and the `/.well-known` discovery endpoints to the handler. `SNOW_MCP_PUBLIC_BASE_URL` must match the externally reachable HTTPS base URL. Configure an exact Entra web redirect URI for its `/auth/callback` endpoint.

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