"""Filesystem tools: read cap clamping, write gate/size cap, mutating ops."""

from __future__ import annotations

from typing import Any

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from helpers import assert_tool_error, make_config, text_of

P = "/pscratch/sd/e/elvis/data.txt"


def _entry(name: str, size: int = 4, kind: str = "file") -> dict[str, Any]:
    return {"name": name, "type": kind, "size": size, "user": "elvis"}


async def test_fs_list_returns_entries(make_server, fake):
    fake.seed_dir("/d", [_entry("a.txt"), _entry("b.txt")])
    server = make_server()
    result = await server.call_tool("fs_list", {"path": "/d"})
    entries = result.structured_content["result"]
    assert [e["name"] for e in entries] == ["a.txt", "b.txt"]
    assert "a.txt" in text_of(result)


async def test_fs_list_limit_truncates(make_server, fake):
    fake.seed_dir("/d", [_entry("a"), _entry("b"), _entry("c")])
    server = make_server()
    result = await server.call_tool("fs_list", {"path": "/d", "limit": 2})
    assert len(result.structured_content["result"]) == 2


async def test_fs_head_returns_content(make_server, fake):
    fake.files[P] = "line one\nline two\n"
    server = make_server()
    result = await server.call_tool("fs_head", {"path": P, "lines": 3})
    assert text_of(result) == "line one\nline two\n"


async def test_fs_head_lines_clamped(make_server, fake):
    fake.files[P] = "x\n"
    server = make_server(config=make_config(max_lines=10))
    await server.call_tool("fs_head", {"path": P, "lines": 200})
    head_params = [
        params
        for method, key, params in fake.param_calls
        if method == "GET" and key.startswith("filesystem/head")
    ]
    assert head_params and all(p["lines"] == "10" for p in head_params)


async def test_fs_tail_lines_clamped(make_server, fake):
    fake.files[P] = "x\n"
    server = make_server(config=make_config(max_lines=10))
    await server.call_tool("fs_tail", {"path": P, "lines": 200})
    tail_params = [
        params
        for method, key, params in fake.param_calls
        if method == "GET" and key.startswith("filesystem/tail")
    ]
    assert tail_params and all(p["lines"] == "10" for p in tail_params)


async def test_fs_read_clamps_requested_bytes(make_server, fake):
    fake.files[P] = "0123456789"
    server = make_server(config=make_config(max_read_bytes=1024))
    result = await server.call_tool("fs_read", {"path": P, "max_bytes": 100_000})
    assert text_of(result) == "0123456789"
    head_params = [
        params
        for method, key, params in fake.param_calls
        if method == "GET" and key.startswith("filesystem/head")
    ]
    assert head_params and all(p["bytes"] == "1024" for p in head_params)


async def test_fs_read_defaults_to_byte_cap(make_server, fake):
    fake.files[P] = "0123456789"
    server = make_server(config=make_config(max_read_bytes=16_384))
    await server.call_tool("fs_read", {"path": P})
    head_params = [
        params
        for method, key, params in fake.param_calls
        if method == "GET" and key.startswith("filesystem/head")
    ]
    assert head_params and all(p["bytes"] == "16384" for p in head_params)


async def test_fs_stat(make_server, fake):
    fake.files[P] = "0123456789"  # 10 bytes
    server = make_server()
    result = await server.call_tool("fs_stat", {"path": P})
    sc = result.structured_content
    assert sc["size"] == 10
    assert sc["path"] == P


async def test_fs_checksum(make_server, fake):
    fake.checksums[P] = "ab" * 32
    server = make_server()
    result = await server.call_tool("fs_checksum", {"path": P})
    assert text_of(result) == "ab" * 32


async def test_fs_write_text_rejected_in_readonly(make_server):
    server = make_server()
    with pytest.raises(ToolError) as exc:
        await server.call_tool("fs_write_text", {"path": P, "content": "hi"})
    assert_tool_error(exc.value, "readonly", "--allow-fs-write")


async def test_fs_write_text_success(make_server, fake):
    server = make_server(config=make_config(allow_fs_write=True))
    result = await server.call_tool("fs_write_text", {"path": P, "content": "hello"})
    assert text_of(result) == "wrote 5 bytes to " + P
    uploads = [key for method, key in fake.calls if key.startswith("filesystem/upload")]
    assert uploads, "upload task was not submitted"


async def test_fs_write_text_over_cap_rejected(make_server):
    server = make_server(config=make_config(allow_fs_write=True, max_write_bytes=8))
    with pytest.raises(ToolError) as exc:
        await server.call_tool("fs_write_text", {"path": P, "content": "123456789"})
    assert_tool_error(exc.value, "9 bytes", "write cap")


async def test_fs_write_text_bytes_counted_in_utf8(make_server):
    server = make_server(config=make_config(allow_fs_write=True, max_write_bytes=4))
    with pytest.raises(ToolError) as exc:
        await server.call_tool("fs_write_text", {"path": P, "content": "héllo"})  # 6 UTF-8 bytes
    assert_tool_error(exc.value, "6 bytes", "write cap")


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("fs_mkdir", {"path": "/d"}),
        ("fs_copy", {"path": "/a", "target_path": "/b"}),
        ("fs_move", {"path": "/a", "target_path": "/b"}),
        ("fs_remove", {"path": "/a"}),
        ("fs_symlink", {"path": "/a", "link_path": "/link"}),
    ],
)
async def test_mutating_tools_rejected_in_readonly(make_server, tool, arguments):
    server = make_server()
    with pytest.raises(ToolError) as exc:
        await server.call_tool(tool, arguments)
    assert_tool_error(exc.value, "--allow-fs-write")


async def test_fs_mkdir_success(make_server, fake):
    server = make_server(config=make_config(allow_fs_write=True))
    result = await server.call_tool("fs_mkdir", {"path": "/d/new"})
    assert "created /d/new" in text_of(result)
    mkdir_bodies = [b for b in fake.bodies if "parent" in b]
    assert mkdir_bodies and mkdir_bodies[-1]["path"] == "/d/new"


async def test_fs_copy_success(make_server, fake):
    server = make_server(config=make_config(allow_fs_write=True))
    result = await server.call_tool("fs_copy", {"path": "/a", "target_path": "/b"})
    assert "copied /a -> /b" in text_of(result)
    cp_bodies = [b for b in fake.bodies if "target_path" in b]
    assert cp_bodies and cp_bodies[-1]["path"] == "/a"


async def test_fs_move_success(make_server, fake):
    server = make_server(config=make_config(allow_fs_write=True))
    result = await server.call_tool("fs_move", {"path": "/a", "target_path": "/b"})
    assert "moved /a -> /b" in text_of(result)
    mv_bodies = [b for b in fake.bodies if "target_path" in b]
    assert mv_bodies and mv_bodies[-1]["path"] == "/a"


async def test_fs_remove_success(make_server, fake):
    server = make_server(config=make_config(allow_fs_write=True))
    result = await server.call_tool("fs_remove", {"path": "/a"})
    assert "removed /a" in text_of(result)
    rm_calls = [key for method, key in fake.calls if key.startswith("filesystem/rm")]
    assert rm_calls


async def test_fs_symlink_success(make_server, fake):
    server = make_server(config=make_config(allow_fs_write=True))
    result = await server.call_tool("fs_symlink", {"path": "/a", "link_path": "/link"})
    assert "symlink /link -> /a" in text_of(result)
    symlink_bodies = [b for b in fake.bodies if "link_path" in b]
    assert symlink_bodies and symlink_bodies[-1]["path"] == "/a"


async def test_fs_read_requires_credentials(make_server):
    server = make_server(access_token=None)
    with pytest.raises(ToolError) as exc:
        await server.call_tool("fs_head", {"path": P, "lines": 5})
    assert_tool_error(exc.value, "no credentials", "IRI_API_TOKEN")