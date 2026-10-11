"""Friendly error mapping for tool handlers.

Client exceptions are converted to actionable ``ToolError`` messages so the MCP
client (the agent) sees the diagnosis, not a bare traceback. ``ToolError`` is
the one exception class the SDK passes through to the client's ``is_error``
content; every other exception becomes an opaque "Error executing tool ...".
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any, TypeVar

import httpx
from iri_client import AuthError, IriError, ResourceLookupError
from mcp.server.mcpserver.exceptions import ToolError

from .safety import PolicyError

_F = TypeVar("_F", bound=Callable[..., Awaitable[Any]])

AUTH_HINT = (
    "no credentials: set IRI_API_TOKEN (or ALCF_API_TOKEN / ESNET_API_TOKEN), "
    "or a token file such as ~/.ssh/nersc-token"
)


def friendly_message(exc: Exception) -> str:
    """Map a client/policy exception to a concise, actionable message."""
    if isinstance(exc, PolicyError):
        return str(exc)
    if isinstance(exc, AuthError):
        return AUTH_HINT
    if isinstance(exc, ResourceLookupError):
        return f"resource lookup failed: {exc}"
    if isinstance(exc, TimeoutError):
        return f"operation timed out: {exc}"
    if isinstance(exc, httpx.HTTPStatusError):
        response = exc.response
        return (
            f"IRI API error: HTTP {response.status_code} {response.reason_phrase} "
            f"for {exc.request.method} {exc.request.url.path}"
        )
    if isinstance(exc, IriError):
        return f"IRI API error: {exc}"
    return f"unexpected error: {type(exc).__name__}: {exc}"


def iri_tool(fn: _F) -> _F:
    """Wrap a tool handler so any raised error becomes a friendly ToolError."""

    @wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return await fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - converted for the client below
            raise ToolError(friendly_message(exc)) from exc

    return wrapper  # type: ignore[return-value]


__all__ = ["iri_tool", "friendly_message", "AUTH_HINT"]