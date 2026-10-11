"""Server assembly: MCPServer("iri"), registration, transports, entrypoint.

Copies on this server describe the caller as "the assistant" / "the agent" —
the server is harness-agnostic.
"""

from __future__ import annotations

import logging
import sys

from mcp.server import MCPServer

from . import __version__
from .config import Config
from .iritools import compute, filesystem, observability
from .prompt import register_prompt
from .runner import IriRunner, Runner

logger = logging.getLogger(__name__)

SERVER_NAME = "iri"
SERVER_TITLE = "NERSC IRI"
SERVER_DESCRIPTION = (
    "Tools for the NERSC Integrated Research Infrastructure (IRI) API: jobs, "
    "files, facility status, and a scientific-workflow prompt."
)

SERVER_INSTRUCTIONS = (
    "You are connected to the NERSC IRI MCP server. Read-only by default: "
    "observability tools and filesystem reads are always available, while job "
    "submission/cancellation and filesystem writes require the operator to have "
    "started the server with --allow-submit / --allow-fs-write. The server "
    "enforces caps on duration, nodes, processes, queue, and read/write sizes "
    "and will reject or clamp requests that exceed them. Check "
    "get_facility_info and get_resource_status first, and use the "
    "conduct-scientific-workflow prompt for the full set of conventions."
)


def build_server(config: Config, runner: Runner | None = None) -> MCPServer:
    """Assemble a fully-registered MCPServer for the given configuration."""
    active = runner if runner is not None else IriRunner(config)
    mcp = MCPServer(
        name=SERVER_NAME,
        title=SERVER_TITLE,
        description=SERVER_DESCRIPTION,
        instructions=SERVER_INSTRUCTIONS,
        version=__version__,
    )
    observability.register(mcp, active)
    compute.register(mcp, active)
    filesystem.register(mcp, active)
    register_prompt(mcp)
    return mcp


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        stream=sys.stderr,
        level=level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def main(argv: list | None = None) -> None:
    """Entrypoint for ``python -m iri_mcp`` / the ``iri-mcp`` console script."""
    config = Config.load(argv)
    _setup_logging(config.log_level)
    logger.info(
        "iri-mcp %s starting transport=%s readonly=%s submit=%s fs_write=%s api=%s",
        __version__,
        config.transport,
        config.readonly,
        config.submit_enabled,
        config.fs_write_enabled,
        config.api_base_url,
    )
    server = build_server(config)
    if config.transport == "streamable-http":
        server.run(transport="streamable-http", host=config.host, port=config.port)
    else:
        server.run(transport="stdio")


__all__ = ["build_server", "main", "SERVER_NAME", "SERVER_TITLE"]