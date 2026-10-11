"""Server assembly and registration: 23 tools, the prompt, and defaults."""

from __future__ import annotations

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from helpers import make_config
from iri_mcp import __version__
from iri_mcp.server import SERVER_NAME, build_server

EXPECTED_TOOLS: set[str] = {
    "get_facility_info",
    "get_facility_sites",
    "get_resource_status",
    "get_incidents",
    "list_projects",
    "submit_job",
    "run_job",
    "list_jobs",
    "get_job",
    "wait_job",
    "cancel_job",
    "fs_list",
    "fs_head",
    "fs_tail",
    "fs_stat",
    "fs_checksum",
    "fs_read",
    "fs_write_text",
    "fs_mkdir",
    "fs_copy",
    "fs_move",
    "fs_remove",
    "fs_symlink",
}


async def _tools(server) -> list[str]:
    tools = await server.list_tools()
    return [t.name for t in tools]


def test_server_identity_and_defaults():
    server = build_server(make_config())
    assert server.name == SERVER_NAME
    assert server.version == __version__
    assert "Read-only by default" in server.instructions


async def test_all_tools_registered(make_server):
    server = make_server()
    names = await _tools(server)
    assert set(names) == EXPECTED_TOOLS
    assert len(names) == 23


async def test_read_tools_available_in_readonly(make_server):
    server = make_server()
    names = await _tools(server)
    assert "fs_head" in names
    assert "fs_read" in names
    assert "submit_job" in names  # registered (but gated at call time)


async def test_prompt_registered(make_server):
    server = make_server()
    prompts = await server.list_prompts()
    assert [p.name for p in prompts] == ["conduct-scientific-workflow"]


async def test_prompt_renders_conventions_and_task(make_server):
    server = make_server()
    result = await server.get_prompt(
        "conduct-scientific-workflow", {"task": "run my sim on Perlmutter"}
    )
    assert len(result.messages) == 3
    texts = [m.content.text for m in result.messages]
    assert any("Orient first" in t for t in texts)
    assert any("run my sim on Perlmutter" in t for t in texts)


async def test_unknown_tool_raises(make_server):
    server = make_server()
    with pytest.raises(ToolError, match="Unknown tool"):
        await server.call_tool("no_such_tool", {})