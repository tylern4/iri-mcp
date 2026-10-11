"""Read-only MCP resources: job status and file contents.

Resources are unprivileged reads — they reuse the same credential-gated read
paths as ``get_job`` / ``fs_read`` and are not behind ``--allow-submit`` /
``--allow-fs-write``. Failures are mapped to friendly messages (same policy as
tool handlers) and surfaced as ``ResourceError`` so the client sees the
diagnosis rather than an opaque internal error.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any, TypeVar

from mcp.server.mcpserver import MCPServer, ResourceSecurity
from mcp.server.mcpserver.exceptions import ResourceError

from ..errors import friendly_message
from ..runner import Runner

_F = TypeVar("_F", bound=Callable[..., Awaitable[str]])


def _friendly(fn: _F) -> _F:
    """Wrap a resource handler so raised errors become friendly ``ResourceError``."""

    @wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> str:
        try:
            return await fn(*args, **kwargs)
        except ResourceError:
            raise
        except Exception as exc:  # noqa: BLE001 - converted for the client below
            raise ResourceError(friendly_message(exc)) from exc

    return wrapper  # type: ignore[return-value]


def register(mcp: MCPServer, runner: Runner) -> None:
    """Register the resource family: job status and file contents."""

    @mcp.resource(
        "iri://jobs/{job_id}",
        name="job",
        title="IRI job status",
        description=(
            "JSON status for a job id: state, exit code, message, and stdout/stderr "
            "tails when available. Requires credentials."
        ),
        mime_type="application/json",
    )
    @_friendly
    async def job_resource(job_id: str) -> str:
        result = await runner.get_job(job_id)  # type: ignore[attr-defined]
        return result.model_dump_json(indent=2)

    @mcp.resource(
        "iri://files{+path}",
        name="file",
        title="IRI file contents",
        description=(
            "Read a small text file from the IRI filesystem (size-capped by the "
            "server's --max-read-bytes). Requires credentials."
        ),
        mime_type="text/plain",
        # Remote paths are absolute by design; still reject traversal and NULs.
        security=ResourceSecurity(reject_absolute_paths=False),
    )
    @_friendly
    async def file_resource(path: str) -> str:
        return await runner.read_file(path)


__all__ = ["register"]
