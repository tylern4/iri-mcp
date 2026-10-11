"""Read-only resources: ``iri://jobs/{job_id}`` and ``iri://files{+path}``."""

from __future__ import annotations

import json

import pytest
from mcp.server.mcpserver.exceptions import ResourceError, ResourceNotFoundError

FILE = "/pscratch/sd/e/elvis/tmp/hello.out"


async def _templates(server) -> set[str]:
    return {t.uri_template for t in await server.list_resource_templates()}


async def _read(server, uri: str) -> str:
    contents = await server.read_resource(uri)
    return "\n".join(c.content for c in contents)


async def test_only_templates_registered(make_server):
    server = make_server()
    assert await _templates(server) == {"iri://jobs/{job_id}", "iri://files{+path}"}


async def test_job_resource_returns_status(make_server, fake):
    fake.seed_job("job-42", state="completed", exit_code=0)
    server = make_server()
    payload = json.loads(await _read(server, "iri://jobs/job-42"))
    assert payload["job_id"] == "job-42"
    assert payload["state"] == "completed"
    assert payload["exit_code"] == 0


async def test_job_resource_missing_id_is_friendly(make_server):
    server = make_server()
    with pytest.raises(ResourceError, match="HTTP 404"):
        await server.read_resource("iri://jobs/missing")


async def test_job_resource_needs_credentials(make_server):
    server = make_server(access_token=None)
    with pytest.raises(ResourceError, match="no credentials"):
        await server.read_resource("iri://jobs/job-42")


async def test_file_resource_reads_absolute_path(make_server, fake):
    fake.files[FILE] = "hello from the fake backend\n"
    server = make_server()
    assert await _read(server, f"iri://files{FILE}") == "hello from the fake backend\n"


async def test_file_resource_needs_credentials(make_server):
    server = make_server(access_token=None)
    with pytest.raises(ResourceError, match="no credentials"):
        await server.read_resource(f"iri://files{FILE}")


async def test_file_resource_rejects_traversal(make_server):
    server = make_server()
    with pytest.raises(ResourceNotFoundError):
        await server.read_resource("iri://files/../../etc/passwd")


async def test_unknown_resource_uri(make_server):
    server = make_server()
    with pytest.raises(ResourceNotFoundError):
        await server.read_resource("iri://nope/whatever")
