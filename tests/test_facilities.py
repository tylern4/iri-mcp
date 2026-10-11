"""Facility selection and resource-discovery strategies.

The fake speaks the same IRI API for every facility, so these tests exercise the
two discovery paths (router vs ``/status/resources``) and the router->status
fallback that ALCF needs (its router discovery endpoints return HTTP 501).
"""

from __future__ import annotations

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from helpers import SPEC, assert_tool_error, make_config
from iri_mcp.schemas import JobSpecInput


async def test_nersc_defaults_to_router_discovery(make_runner, fake):
    runner = make_runner(allow_submit=True)
    result = await runner.submit(JobSpecInput(**SPEC))
    assert result.job_id == "job-1"
    assert ("GET", "compute/resources") in fake.calls
    assert ("GET", "status/resources") not in fake.calls


async def test_alcf_uses_status_discovery(make_runner, fake):
    runner = make_runner(allow_submit=True, facility="alcf")
    result = await runner.submit(JobSpecInput(**SPEC))
    assert result.job_id == "job-1"
    assert ("GET", "status/resources") in fake.calls
    assert ("GET", "compute/resources") not in fake.calls


async def test_router_501_falls_back_to_status(make_runner, fake):
    fake.discovery_status = 501
    runner = make_runner(allow_submit=True)
    result = await runner.submit(JobSpecInput(**SPEC))
    assert result.job_id == "job-1"
    assert ("GET", "compute/resources") in fake.calls
    assert ("GET", "status/resources") in fake.calls


async def test_status_discovery_matches_case_insensitively(make_runner):
    runner = make_runner(
        allow_submit=True,
        facility="alcf",
        compute_resource="perlmutter",  # resource name in /status/resources
        filesystem_resource="perlmutter scratch",
    )
    result = await runner.submit(JobSpecInput(**SPEC))
    assert result.job_id == "job-1"


async def test_filesystem_uses_status_discovery(make_runner, fake):
    fake.seed_dir("/d", [])
    runner = make_runner(facility="alcf")
    assert await runner.fs_list("/d") == []
    assert ("GET", "status/resources") in fake.calls
    assert ("GET", "filesystem/resources") not in fake.calls


async def test_unresolvable_resource_lists_alternatives(make_server):
    cfg = make_config(allow_submit=True, facility="alcf", compute_resource="nope")
    server = make_server(cfg)
    with pytest.raises(ToolError) as exc:
        await server.call_tool("submit_job", {"spec": dict(SPEC)})
    assert_tool_error(exc.value, "no compute resource", "Perlmutter")
