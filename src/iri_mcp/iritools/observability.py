"""Observability tools: facility/status/capacity (token-free public endpoints)."""

from __future__ import annotations

from mcp.server import MCPServer

from ..errors import iri_tool
from ..runner import Runner


def register(mcp: MCPServer, runner: Runner) -> None:
    """Register the observability tool family."""

    @mcp.tool()
    @iri_tool
    async def get_facility_info() -> dict:
        """Fetch metadata about the configured IRI facility.

        Read-only and requires no credentials. A good first call: confirms the
        assistant can reach the facility API and returns the facility name,
        organization, and support link.
        """
        return await runner.facility_info()

    @mcp.tool()
    @iri_tool
    async def get_facility_sites() -> list:
        """List the sites served by the configured IRI facility.

        Read-only and requires no credentials. Returns site metadata such as
        operating organization and location.
        """
        return await runner.facility_sites()

    @mcp.tool()
    @iri_tool
    async def get_resource_status() -> dict:
        """Get the current status of IRI compute and storage resources.

        Read-only and requires no credentials. Returns the resource list with
        current status plus a name -> status map. Check this before submitting
        work so the assistant does not act on a down resource.
        """
        return await runner.resource_status()

    @mcp.tool()
    @iri_tool
    async def get_incidents() -> list:
        """List planned and unplanned incidents affecting IRI resources.

        Read-only and requires no credentials.
        """
        return await runner.incidents()

    @mcp.tool()
    @iri_tool
    async def list_projects() -> list:
        """List the IRI projects the authenticated user belongs to.

        Requires credentials (a facility bearer token; see the README for the
        per-facility environment variable or token file). Use this to discover
        valid ``account`` values before submitting a job; never invent an
        account.
        """
        return await runner.projects()


__all__ = ["register"]