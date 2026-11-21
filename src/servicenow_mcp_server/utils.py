# src/servicenow_mcp_server/utils.py

import httpx
import logging
import os
from typing import Dict, Any, Awaitable, Callable, Optional
from urllib.parse import urlsplit
from pydantic import BaseModel

logger = logging.getLogger(__name__)
if os.getenv("LOGLEVEL", "").upper() == "DEBUG":
    logger.setLevel(logging.DEBUG)


class ServiceNowToolParams(BaseModel):
    """Base for business-only tool inputs with runtime connection settings."""

    @property
    def instance_url(self) -> str:
        return os.environ["SERVICENOW_INSTANCE"]

    @property
    def username(self) -> None:
        return None

    @property
    def password(self) -> None:
        return None

class ServiceNowClient:
    """A client for making authenticated requests to the ServiceNow API."""

    def __init__(
        self,
        instance_url: str,
        username: Optional[str] = None,
        password: Optional[str] = None,
        token_provider: Optional[Callable[[], Awaitable[str]]] = None,
    ):
        parsed_url = urlsplit(instance_url)
        if (
            parsed_url.scheme != "https"
            or not parsed_url.hostname
            or parsed_url.username is not None
            or parsed_url.password is not None
            or parsed_url.query
            or parsed_url.fragment
        ):
            raise ValueError("ServiceNow instance URL must be an HTTPS URL without credentials, query or fragment.")
        if not instance_url.endswith('/'):
            instance_url += '/'
        
        self.base_url = instance_url
        if username is not None or password is not None:
            raise ValueError("Basic authentication is no longer supported.")
        if token_provider is None:
            from servicenow_mcp_server.auth import get_servicenow_access_token

            token_provider = get_servicenow_access_token
        self._token_provider = token_provider
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self):
        """Initializes the httpx client when entering an 'async with' block."""
        
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self._token_provider:
            access_token = await self._token_provider()
            if not access_token:
                raise RuntimeError("The token provider returned an empty access token.")
            headers["Authorization"] = f"Bearer {access_token}"
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=headers,
            verify=True,
        )
        
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Closes the httpx client when exiting an 'async with' block."""
        if self._client:
            await self._client.aclose()

    async def _request(self, method, endpoint, **kwargs):
        path = urlsplit(endpoint).path
        logger.debug("ServiceNow API request: %s %s", method, path)
        try:
            response = await self._client.request(method=method, url=endpoint, **kwargs)
        except Exception as exc:
            logger.debug("ServiceNow API request failed: %s %s (%s)", method, path, type(exc).__name__)
            raise
        logger.debug("ServiceNow API response: %s %s status=%s", method, path, response.status_code)
        return response
    
    async def send_request(self, method: str, endpoint: str, data: Optional[Dict[str, Any]] = None, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Sends an API request to a ServiceNow endpoint."""
        if not self._client:
            raise RuntimeError("Client not initialized. Use 'async with ServiceNowClient(...)'")
        try:
            response = await self._request(method, endpoint, json=data, params=params, headers={"Accept": "application/json", "Content-Type": "application/json"})
            response.raise_for_status()

            # THE FIX: Handle successful but empty responses (like from DELETE)
            if response.status_code == 204:
                return {"result": {"status": "success", "message": "Operation completed successfully with no content returned."}}
            return response.json()
        except httpx.HTTPStatusError as e:
            return {"error": "ServiceNow API Error", "status_code": e.response.status_code, "details": e.response.text}
        except Exception as e:
            return {"error": "Request failed", "details": str(e)}
        
    async def send_raw_request(self, method: str, endpoint: str, params: Optional[Dict[str, Any]] = None, data: Optional[bytes] = None, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """Sends a request with raw data, for file uploads."""
        if not self._client:
            raise RuntimeError("Client not initialized. Use 'async with ServiceNowClient(...)'")
        
        final_headers = {"Accept": "application/json"}
        if headers:
            final_headers.update(headers)
            
        try:
            response = await self._request(
                method,
                endpoint,
                params=params,
                content=data,
                headers=final_headers
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            return {"error": "ServiceNow API Error", "status_code": e.response.status_code, "details": e.response.text}
        except Exception as e:
            return {"error": "Request failed", "details": str(e)}