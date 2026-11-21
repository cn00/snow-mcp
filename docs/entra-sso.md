# Entra SSO setup

This branch exposes an authenticated MCP server over Streamable HTTP. Tool inputs no longer accept a ServiceNow instance URL, username, or password. Existing Basic authentication and stdio client examples in README.md and How2Use.md do not apply to this branch.

## Prerequisites

- Python 3.10 or later, an HTTPS endpoint for the MCP server, and access from the target Copilot client.
- A single-tenant Microsoft Entra application with a client secret and an exposed delegated API scope for the MCP server. Configure v2 access tokens for this API and register `<public-base-url><service-prefix>/auth/callback` as a web redirect URI.
- A ServiceNow API resource that accepts the delegated Entra token or SAML 2.0 assertion acquired using the on-behalf-of (OBO) flow. Confirm its authentication method, audience, scope, user mapping, and ACLs with the ServiceNow and identity administrators. This repository does not establish that the target instance supports either integration.

## Configuration

Supply the following environment variables to the server through your deployment's secret management. Do not commit credentials.

| Variable | Description |
| --- | --- |
| `SERVICENOW_INSTANCE` | HTTPS URL of the ServiceNow instance. |
| `SERVICENOW_AUTH_MODE` | Downstream authentication mode: `oauth` (default) or `saml` for an Entra SAML 2.0 OBO assertion. |
| `SERVICENOW_OBO_SCOPE` | OAuth mode: delegated scope for the ServiceNow API resource. SAML mode: the target SAML Entity ID followed by `/.default`. |
| `SNOW_ENTRA_TENANT_ID` | Entra tenant UUID. |
| `SNOW_ENTRA_CLIENT_ID` | MCP application's Entra client UUID. |
| `SNOW_ENTRA_CLIENT_SECRET` | MCP application's client secret. |
| `SNOW_ENTRA_MCP_SCOPE` | Unprefixed delegated scope name exposed by the MCP app, for example `mcp_access`. |
| `SNOW_ENTRA_IDENTIFIER_URI` | Optional application ID URI; defaults to `api://<client-id>`. |
| `SNOW_MCP_PUBLIC_BASE_URL` | External HTTPS origin without a path, for example `https://mcp.example.com`; loopback HTTP is allowed for development. |
| `SNOW_MCP_SERVICE_PREFIX` | Optional public path prefix, for example `/snow`; also stripped from forwarded Lambda paths when present. |
| `SNOW_MCP_JWT_SIGNING_KEY` | Stable, high-entropy secret of at least 32 characters used by the OAuth proxy. |
| `SNOW_MCP_REDIS_URL` | Optional Redis URL for shared OAuth state. Remote servers require `rediss://`; `redis://` is allowed only for loopback development. Query parameters are not supported. |
| `SNOW_MCP_REDIS_ENCRYPTION_KEY` | Fernet key for encrypting OAuth data in Redis, required when `SNOW_MCP_REDIS_URL` is set. Use the same stable secret across instances. |
| `LOGLEVEL` | Set to `DEBUG` to log ServiceNow request methods, API paths and response statuses. Query parameters, request bodies and authorization headers are not logged. |

The MCP application must have the necessary delegated permission and consent for `SERVICENOW_OBO_SCOPE`. The outbound request uses an OBO token, not the client-facing MCP token. The HTTPS certificate presented by ServiceNow must be trusted by the Python environment.

For `SERVICENOW_AUTH_MODE=saml`, obtain the target service's SAML Entity ID from its SSO configuration and use, for example, `SERVICENOW_OBO_SCOPE=https://saml.example.com/.default`. The Entity ID may differ from the Entra application's Identifier URI; the `user_impersonation` scope is not the SAML OBO scope. Entra must permit the MCP application to request the target resource with consent. The client requests a SAML 2.0 assertion and sends the returned base64url assertion as `Authorization: Bearer` to ServiceNow. This mode is only usable if the specific ServiceNow REST API accepts that form of SAML bearer assertion; browser SAML SSO and an Entra application registration do not establish REST API support. It does not create a browser session or exchange a SAML assertion for a ServiceNow-issued OAuth token. Confirm the recipient, audience, user mapping and API authentication contract with the ServiceNow and Entra administrators before enabling it.

```dotenv
SERVICENOW_AUTH_MODE=saml
SERVICENOW_OBO_SCOPE=https://saml.example.com/.default
```

Replace the example with the verified SAML Entity ID. The provider caches its configuration, so recreate the service after changing the mode or scope. Leave `SERVICENOW_AUTH_MODE` unset or set it to `oauth` to retain the existing OAuth behavior.

API paths may contain record identifiers, so protect debug logs accordingly. Authentication or token exchange failures occurring before an HTTP request will not produce an API request log.

When an Entra OBO exchange fails, the server logs the OAuth error category, validated AADSTS error codes and trace/correlation IDs when available. It does not log the assertion, client secret, token, or provider error description. Use the AADSTS code and correlation ID to check Entra sign-in logs and delegated permissions; a successful MCP login alone does not establish that ServiceNow accepts the exchanged token.

Generate a Redis encryption key with `python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'` and store it as a secret. Do not generate a new key per invocation. Use a dedicated Redis database or instance for this MCP deployment; the OAuth storage collection names are shared. Rotating the encryption key or replacing local storage invalidates existing OAuth state, so clients may need to register and sign in again.

## Run

```bash
python -m pip install -e .
snow-mcp --host 127.0.0.1 --port 8000
```

Build and run the standalone image without mounting a host virtual environment or source tree:

```bash
docker build -t snow-mcp:local .
docker run --rm --env-file .env -p 3000:8080 snow-mcp:local
```

Set `SNOW_MCP_PUBLIC_BASE_URL` in the environment to the public origin used by the client, for example `http://localhost:3000` for local testing. The image stores local OAuth state under `/tmp/snow-mcp`; mount persistent storage there or configure shared Redis if state must survive container replacement. The image does not include credentials from `.env`.

If dependency downloads require an enterprise proxy CA, provide a trusted CA bundle as a BuildKit secret instead of disabling TLS verification:

```bash
docker build --secret id=pip_ca,src=/path/to/trusted-ca-bundle.pem -t snow-mcp:local .
```

The build-time CA secret is not installed into the runtime image. Configure runtime trust separately when the ServiceNow or Entra connection requires an enterprise CA.

For local Compose development, install dependencies into a Linux Python 3.12 `.venv` and configure the required environment variables in `.env`, then run `docker compose up -d api`. Configure `SNOW_MCP_PUBLIC_BASE_URL` to match the host address and port in your Compose configuration. The standalone server accepts requests with the configured service prefix, or with the prefix stripped by a reverse proxy. Any reverse proxy must also forward the root-level discovery routes.

If an approved enterprise TLS inspection CA is required, export its trusted root certificate to `certs/zscaler-root.pem` and combine it with the existing public CA bundle:

```bash
openssl crl2pkcs7 -nocrl -certfile .venv/lib/python3.12/site-packages/certifi/cacert.pem -certfile certs/zscaler-root.pem -outform DER | openssl pkcs7 -inform DER -print_certs -out certs/zscaler-ca-bundle.pem
docker compose -f docker-compose.yaml -f docker-compose.zscaler.yaml up -d --no-deps api
```

The optional override mounts this generated bundle read-only for HTTPX and Requests. Certificate files under `certs/` are local and ignored by Git. Rebuild the bundle after updating the public CA bundle or rotating the enterprise root certificate. Use only a root certificate verified by your organization; do not disable TLS verification.

For a single local instance, leave `SNOW_MCP_REDIS_URL` unset to use local OAuth storage. That storage is not shared and may be lost when the container is recreated. The Redis service in the local Compose example does not configure TLS and cannot be used with `rediss://`; configure a TLS-enabled Redis endpoint and `SNOW_MCP_REDIS_ENCRYPTION_KEY` before enabling shared storage.

Terminate TLS at a trusted reverse proxy and route the MCP endpoint, OAuth endpoints, and `/.well-known` discovery paths to the service. Prevent clients from bypassing the proxy. The public MCP URL is `<public-base-url><service-prefix>/mcp`; the prefix is empty when unset. For an existing deployment with a path in `SNOW_MCP_PUBLIC_BASE_URL`, move that path to `SNOW_MCP_SERVICE_PREFIX`; a base URL containing a path is rejected. Configure Redis for shared OAuth state across replicas; otherwise the default storage is local and is not shared.

`snow-mcp --list-tools` uses an internal stdio process to list tools; normal tool calls require authenticated HTTP.

## Connect clients

In VS Code Copilot, add the HTTPS MCP URL as an HTTP server and complete the OAuth browser flow. In Copilot Studio, add the existing MCP server and select OAuth 2.0 Dynamic discovery. Actual compatibility, tenant policies, client registration, consent, and redirect handling must be verified in each target environment.

## Verification

Before production, test discovery and sign-in from both clients, token refresh and revocation, and a representative tool call for two users with different ServiceNow permissions. A successful MCP login alone does not prove that the ServiceNow OBO token is accepted or that ServiceNow enforces each user's ACLs. If OBO is unsupported, the server denies the tool call rather than falling back to a shared account.