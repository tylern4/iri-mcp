"""Observability tools: facility/sites/status/incidents (public) and projects."""

from __future__ import annotations

import json
from typing import Any

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from helpers import assert_tool_error, text_of


def _json(result: Any) -> Any:
    """Parse the JSON text content of a result (dicts/lists have no structured)."""
    return json.loads(text_of(result))


async def test_get_facility_info(make_server):
    server = make_server()
    result = await server.call_tool("get_facility_info", {})
    assert result.is_error is False
    data = _json(result)
    assert data["name"] == "NERSC"
    assert data["organization_name"] == "Lawrence Berkeley National Laboratory"
    assert data["id"] == "urn:iri:facility:nersc"


async def test_get_facility_sites(make_server):
    server = make_server()
    result = await server.call_tool("get_facility_sites", {})
    text = text_of(result)
    assert "Perlmutter" in text
    assert "urn:site:perlmutter" in text


async def test_get_resource_status(make_server):
    server = make_server()
    result = await server.call_tool("get_resource_status", {})
    data = _json(result)
    assert len(data["resources"]) == 2
    assert data["statuses"] == {"Perlmutter": "up", "Perlmutter Scratch": "unknown"}
    assert "unknown" in text_of(result)


async def test_get_incidents(make_server):
    server = make_server()
    result = await server.call_tool("get_incidents", {})
    assert "Planned maintenance" in text_of(result)


async def test_list_projects(make_server):
    server = make_server()
    result = await server.call_tool("list_projects", {})
    text = text_of(result)
    assert "Climate Simulation" in text
    assert "proj-abc123" in text


async def test_observability_requires_no_token(make_server):
    server = make_server(access_token=None)
    result = await server.call_tool("get_facility_info", {})
    assert result.is_error is False
    assert "NERSC" in text_of(result)


async def test_list_projects_requires_credentials(make_server):
    server = make_server(access_token=None)
    with pytest.raises(ToolError) as exc:
        await server.call_tool("list_projects", {})
    assert_tool_error(exc.value, "no credentials", "IRI_API_TOKEN")