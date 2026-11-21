"""Entra OAuth configuration and ServiceNow on-behalf-of token exchange."""

import asyncio
import logging
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from threading import Lock
from urllib.parse import urlsplit
from uuid import UUID

logger = logging.getLogger(__name__)
SAML2_TOKEN_TYPE = "urn:ietf:params:oauth:token-type:saml2"


def get_service_prefix():
    prefix = os.getenv("SNOW_MCP_SERVICE_PREFIX", "").rstrip("/")
    if not prefix:
        return ""
    if not re.fullmatch(r"/[A-Za-z0-9._~-]+(?:/[A-Za-z0-9._~-]+)*", prefix) or any(
        segment in {".", ".."} for segment in prefix.split("/")
    ):
        raise ValueError("SNOW_MCP_SERVICE_PREFIX must be an absolute URL path prefix.")
    return prefix


@dataclass(frozen=True)
class EntraMcpConfig:
    tenant_id: str
    client_id: str
    client_secret: str
    identifier_uri: str
    delegated_scope: str
    public_base_url: str
    jwt_signing_key: str

    @classmethod
    def from_environment(cls):
        tenant_id = str(UUID(os.environ["SNOW_ENTRA_TENANT_ID"]))
        client_id = str(UUID(os.environ["SNOW_ENTRA_CLIENT_ID"]))
        client_secret = os.environ["SNOW_ENTRA_CLIENT_SECRET"]
        identifier_uri = os.getenv("SNOW_ENTRA_IDENTIFIER_URI", f"api://{client_id}")
        delegated_scope = os.environ["SNOW_ENTRA_MCP_SCOPE"]
        public_base_url = os.environ["SNOW_MCP_PUBLIC_BASE_URL"]
        jwt_signing_key = os.environ["SNOW_MCP_JWT_SIGNING_KEY"]

        parsed_url = urlsplit(public_base_url)
        local_http = parsed_url.scheme == "http" and parsed_url.hostname in {
            "localhost",
            "127.0.0.1",
            "::1",
        }
        if (
            (parsed_url.scheme != "https" and not local_http)
            or not parsed_url.hostname
            or parsed_url.username
            or parsed_url.password
            # or parsed_url.path not in ("", "/")
            or parsed_url.query
            or parsed_url.fragment
        ):
            print("SNOW_MCP_PUBLIC_BASE_URL should be an HTTPS origin without a path.")
        public_base_url = public_base_url.rstrip("/") + get_service_prefix()
        if not identifier_uri or any(char.isspace() for char in identifier_uri):
            raise ValueError("SNOW_ENTRA_IDENTIFIER_URI is invalid.")
        if not delegated_scope or "/" in delegated_scope or any(
            char.isspace() for char in delegated_scope
        ):
            raise ValueError("SNOW_ENTRA_MCP_SCOPE must be an unprefixed scope name.")
        if len(client_secret) == 0:
            raise ValueError("SNOW_ENTRA_CLIENT_SECRET is required.")
        if len(jwt_signing_key) < 32:
            raise ValueError("SNOW_MCP_JWT_SIGNING_KEY must be at least 32 characters.")

        return cls(
            tenant_id=tenant_id,
            client_id=client_id,
            client_secret=client_secret,
            identifier_uri=identifier_uri,
            delegated_scope=delegated_scope,
            public_base_url=public_base_url,
            jwt_signing_key=jwt_signing_key,
        )


class EntraOnBehalfOfTokenProvider:
    """Exchanges an authenticated Entra assertion for a ServiceNow API token."""

    def __init__(self, tenant_id, client_id, client_secret, service_now_scope, client_app=None, auth_mode="oauth"):
        if not isinstance(auth_mode, str) or auth_mode.lower() not in {"oauth", "saml"}:
            raise ValueError("SERVICENOW_AUTH_MODE must be oauth or saml.")
        self._auth_mode = auth_mode.lower()
        if not service_now_scope or any(char.isspace() for char in service_now_scope):
            raise ValueError("SERVICENOW_OBO_SCOPE must be a non-empty OAuth scope.")
        if self._auth_mode == "saml" and (
            not service_now_scope.endswith("/.default") or len(service_now_scope) <= len("/.default")
        ):
            raise ValueError("SAML mode requires the SAML Entity ID followed by /.default.")
        if client_app is None:
            import msal

            options = {"exclude_scopes": ["profile", "offline_access"]} if self._auth_mode == "saml" else {}
            client_app = msal.ConfidentialClientApplication(
                client_id=client_id,
                authority=f"https://login.microsoftonline.com/{tenant_id}",
                client_credential=client_secret,
                **options,
            )
        self._client_app = client_app
        self._service_now_scope = service_now_scope
        self._lock = Lock()

    async def __call__(self, assertion):
        return await asyncio.to_thread(self._exchange, assertion)

    def _exchange(self, assertion):
        options = {"data": {"requested_token_type": SAML2_TOKEN_TYPE}} if self._auth_mode == "saml" else {}
        with self._lock:
            result = self._client_app.acquire_token_on_behalf_of(
                user_assertion=assertion,
                scopes=[self._service_now_scope],
                **options,
            )
        access_token = result.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            error = result.get("error")
            if not isinstance(error, str) or error not in {
                "access_denied", "consent_required", "interaction_required", "invalid_client",
                "invalid_grant", "invalid_request", "invalid_scope", "login_required",
                "server_error", "temporarily_unavailable", "unauthorized_client",
            }:
                error = "unknown"
            error_codes = result.get("error_codes")
            codes = []
            if isinstance(error_codes, list):
                codes = [
                    code for code in error_codes[:8]
                    if type(code) is int and 0 < code < 100000000
                ]
            description = result.get("error_description")
            if isinstance(description, str):
                match = re.search(r"\bAADSTS([0-9]{5,8})\b", description)
                if match and int(match.group(1)) not in codes:
                    codes.append(int(match.group(1)))
            identifiers = []
            for name in ("trace_id", "correlation_id"):
                value = result.get(name)
                try:
                    identifiers.append(str(UUID(value)) if isinstance(value, str) else "unavailable")
                except ValueError:
                    identifiers.append("unavailable")
            logger.warning(
                "Entra OBO exchange failed: error=%s aadsts_codes=%s trace_id=%s correlation_id=%s",
                error, codes, *identifiers,
            )
            raise RuntimeError("Entra could not issue a delegated ServiceNow token.")
        if self._auth_mode == "saml" and (
            result.get("issued_token_type") != SAML2_TOKEN_TYPE
            or str(result.get("token_type", "")).lower() != "bearer"
            or not re.fullmatch(r"[A-Za-z0-9_-]+={0,2}", access_token)
        ):
            raise RuntimeError("Entra did not issue a valid SAML 2.0 bearer assertion.")
        return access_token


def build_mcp_auth():
    """Create the Entra-backed OAuth proxy used by remote MCP clients."""
    from fastmcp.server.auth.providers.azure import AzureProvider

    config = EntraMcpConfig.from_environment()
    client_storage, redis_client = _build_redis_storage()
    provider = AzureProvider(
        client_id=config.client_id,
        client_secret=config.client_secret,
        tenant_id=config.tenant_id,
        identifier_uri=config.identifier_uri,
        required_scopes=[config.delegated_scope],
        base_url=config.public_base_url,
        jwt_signing_key=config.jwt_signing_key,
        client_storage=client_storage,
    )
    provider._snow_redis_client = redis_client
    return provider


def _build_redis_storage():
    redis_url = os.getenv("SNOW_MCP_REDIS_URL")
    if not redis_url:
        return None, None

    parsed_url = urlsplit(redis_url)
    if (
        parsed_url.scheme not in {"redis", "rediss"}
        or not parsed_url.hostname
        or parsed_url.query
        or parsed_url.fragment
        or (parsed_url.scheme == "redis" and parsed_url.hostname not in {"localhost", "127.0.0.1", "::1"})
    ):
        raise ValueError("SNOW_MCP_REDIS_URL must use rediss://, except for local loopback.")

    from cryptography.fernet import Fernet
    from key_value.aio.stores.redis import RedisStore
    from key_value.aio.wrappers.encryption import FernetEncryptionWrapper
    from redis.asyncio import Redis

    encryption_key = os.environ["SNOW_MCP_REDIS_ENCRYPTION_KEY"]
    fernet = Fernet(encryption_key.encode("ascii"))
    redis_client = Redis.from_url(redis_url, decode_responses=True)
    storage = FernetEncryptionWrapper(RedisStore(client=redis_client), fernet=fernet)
    return storage, redis_client


@lru_cache(maxsize=1)
def _service_now_token_provider():
    tenant_id = str(UUID(os.environ["SNOW_ENTRA_TENANT_ID"]))
    client_id = str(UUID(os.environ["SNOW_ENTRA_CLIENT_ID"]))
    return EntraOnBehalfOfTokenProvider(
        tenant_id=tenant_id,
        client_id=client_id,
        client_secret=os.environ["SNOW_ENTRA_CLIENT_SECRET"],
        service_now_scope=os.environ["SERVICENOW_OBO_SCOPE"],
        auth_mode=os.getenv("SERVICENOW_AUTH_MODE", "oauth"),
    )


async def get_servicenow_access_token():
    """Exchange the authenticated Entra token for a ServiceNow-audience token."""
    from fastmcp.server.dependencies import get_access_token

    access_token = get_access_token()
    if access_token is None or not access_token.token:
        raise RuntimeError("An authenticated Entra user is required.")
    return await _service_now_token_provider()(access_token.token)