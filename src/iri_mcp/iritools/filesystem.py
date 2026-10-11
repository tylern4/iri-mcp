"""Filesystem tools: reads (all modes) and gated writes (``--allow-fs-write``)."""

from __future__ import annotations

from typing import Any

from mcp.server import MCPServer

from ..errors import iri_tool
from ..runner import Runner


def register(mcp: MCPServer, runner: Runner) -> None:
    """Register the filesystem tool family."""

    @mcp.tool()
    @iri_tool
    async def fs_list(path: str, limit: int = 50) -> list[dict[str, Any]]:
        """List entries in a remote directory.

        Returns entry dicts (name, type, size, ...), truncated to ``limit``.
        Requires credentials.
        """
        return await runner.fs_list(path, limit)

    @mcp.tool()
    @iri_tool
    async def fs_head(path: str, lines: int = 10) -> str:
        """Return the first ``lines`` lines of a remote file (line-capped)."""
        return await runner.fs_head(path, lines)

    @mcp.tool()
    @iri_tool
    async def fs_tail(path: str, lines: int = 10) -> str:
        """Return the last ``lines`` lines of a remote file (line-capped).

        Use this to read job errors from stderr files after a failed run.
        """
        return await runner.fs_tail(path, lines)

    @mcp.tool()
    @iri_tool
    async def fs_stat(path: str) -> dict[str, Any]:
        """Return stat metadata for a remote file or directory."""
        return await runner.fs_stat(path)

    @mcp.tool()
    @iri_tool
    async def fs_checksum(path: str) -> str:
        """Return the SHA-256 checksum of a remote file.

        Useful to verify that a produced output matches an expected value.
        """
        return await runner.checksum(path)

    @mcp.tool()
    @iri_tool
    async def fs_read(path: str, max_bytes: int | None = None) -> str:
        """Read a small text file as a string.

        The request is capped at the server's ``--max-read-bytes`` limit so the
        assistant cannot accidentally pull very large files. Prefer ``fs_head`` /
        ``fs_tail`` for big outputs.
        """
        return await runner.read_file(path, max_bytes)

    @mcp.tool()
    @iri_tool
    async def fs_write_text(path: str, content: str) -> str:
        """Write ``content`` to a remote file as UTF-8 text.

        Requires ``--allow-fs-write``. Sized against the server's
        ``--max-write-bytes`` cap. Intended for writing job scripts and small
        inputs; there is no upload of local files.
        """
        return await runner.fs_write_text(path, content)

    @mcp.tool()
    @iri_tool
    async def fs_mkdir(path: str, parent: bool = True) -> str:
        """Create a remote directory (and parents when ``parent`` is true).

        Requires ``--allow-fs-write``.
        """
        return await runner.fs_mkdir(path, parent)

    @mcp.tool()
    @iri_tool
    async def fs_copy(path: str, target_path: str) -> str:
        """Copy a remote path to ``target_path``. Requires ``--allow-fs-write``."""
        return await runner.fs_copy(path, target_path)

    @mcp.tool()
    @iri_tool
    async def fs_move(path: str, target_path: str) -> str:
        """Move a remote path to ``target_path``. Requires ``--allow-fs-write``."""
        return await runner.fs_move(path, target_path)

    @mcp.tool()
    @iri_tool
    async def fs_remove(path: str) -> str:
        """Remove a remote file, directory, or symlink. Requires ``--allow-fs-write``."""
        return await runner.fs_remove(path)

    @mcp.tool()
    @iri_tool
    async def fs_symlink(path: str, link_path: str) -> str:
        """Create symlink ``link_path`` pointing at ``path``.

        Requires ``--allow-fs-write``.
        """
        return await runner.fs_symlink(path, link_path)


__all__ = ["register"]