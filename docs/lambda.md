# AWS Lambda entry point

The Lambda handler is `servicenow_mcp_server.lambda_handler.handler`. Package the project and its dependencies, including Mangum, in the Lambda deployment artifact. Configure the Entra and ServiceNow environment variables described in [entra-sso.md](entra-sso.md).

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