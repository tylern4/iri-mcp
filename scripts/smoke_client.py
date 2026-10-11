"""Offline MCP smoke client: drive a real iri-mcp server over stdio.

Spawns ``python -m iri_mcp`` pointed at the fake backend and exercises the
protocol the same way a harness would: initialize, ``tools/list``, one
observability call, one compute call (``run_job`` with tails), and one
filesystem read. Fails loudly (non-zero exit) on any mismatch.

Usage:
    uv run python scripts/smoke_client.py \
        --base-url http://127.0.0.1:8971/api/v1 [--allow-submit] [--allow-fs-write]
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import CallToolResult

OUT = "/pscratch/sd/e/elvis/tmp/hello.out"
ERR = "/pscratch/sd/e/elvis/tmp/hello.err"
SPEC = {
    "name": "hello",
    "executable": "/bin/echo",
    "arguments": ["hello iri"],
    "directory": "/pscratch/sd/e/elvis/tmp",
    "stdout_path": OUT,
    "stderr_path": ERR,
    "account": "m0000",
    "queue_name": "debug",
    "duration": 60,
    "node_count": 1,
    "processes_per_node": 1,
}


def _text(result: CallToolResult) -> str:
    parts = []
    for block in result.content:
        text = getattr(block, "text", None)
        if text is not None:
            parts.append(text)
    return "\n".join(parts)


def _check(label: str, condition: bool, detail: str = "") -> None:
    if not condition:
        print(f"FAIL {label}" + (f": {detail}" if detail else ""))
        sys.exit(1)
    print(f"ok   {label}")


async def _call(session: ClientSession, name: str, arguments: dict[str, Any]) -> CallToolResult:
    result = await session.call_tool(name, arguments)
    assert not result.is_error, f"tool {name} failed: {_text(result)}"
    return result


async def run(base_url: str, allow_submit: bool, allow_fs_write: bool) -> None:
    command = [
        "uv",
        "run",
        "python",
        "-m",
        "iri_mcp",
        "--api-base-url",
        base_url,
        "--wait-interval",
        "0.05",
        "--log-level",
        "WARNING",
    ]
    if allow_submit:
        command.append("--allow-submit")
    if allow_fs_write:
        command.append("--allow-fs-write")
    params = StdioServerParameters(
        command="uv",
        args=command[1:],
        # The SDK only inherits an env allowlist; the server needs the caller's
        # full environment (IRI_API_TOKEN, proxy vars, ...).
        env=dict(os.environ),
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            server_info = session.initialize_result.server_info
            print(f"connected to server {server_info.name} {server_info.version}")

            tools = await session.list_tools()
            names = sorted(tool.name for tool in tools.tools)
            _check("tools/list exposes 23 tools", len(names) == 23, str(names))
            expected = {
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
            _check("tools/list names match contract", set(names) == expected)

            prompts = await session.list_prompts()
            prompt_names = [p.name for p in prompts.prompts]
            _check("prompts/list has conduct-scientific-workflow",
                   "conduct-scientific-workflow" in prompt_names, str(prompt_names))

            facility = _text(await _call(session, "get_facility_info", {}))
            _check("get_facility_info returns NERSC", '"NERSC"' in facility)

            resources = _text(await _call(session, "get_resource_status", {}))
            _check("get_resource_status lists resources", '"resources"' in resources)

            projects = _text(await _call(session, "list_projects", {}))
            _check("list_projects returns a project", '"Climate Simulation"' in projects)

            submitted = await _call(session, "submit_job", {"spec": SPEC})
            job_id = submitted.structured_content["job_id"]
            _check("submit_job returns job_id", bool(job_id), str(submitted.structured_content))

            ran = await _call(session, "run_job", {"spec": SPEC, "timeout": 5.0})
            sc = ran.structured_content
            _check("run_job reaches completed", sc["state"] == "completed", str(sc))
            _check("run_job exit code 0", sc["exit_code"] == 0, str(sc))
            _check("run_job returns stdout tail",
                   sc["stdout_tail"] == "hello from the fake backend\n", str(sc))

            waiting = await _call(session, "wait_job", {"job_id": job_id, "timeout": 5.0})
            _check("wait_job completes submitted job",
                   waiting.structured_content["state"] == "completed",
                   str(waiting.structured_content))

            head = _text(await _call(session, "fs_head", {"path": OUT, "lines": 5}))
            _check("fs_head reads the output file", "hello from the fake backend" in head)

            checksum = _text(await _call(session, "fs_checksum", {"path": OUT}))
            _check("fs_checksum returns hex checksum", "d1" * 32 == checksum, checksum)

            templates = await session.list_resource_templates()
            template_uris = {t.uri_template for t in templates.resource_templates}
            _check(
                "resources/templates exposes job + file templates",
                template_uris == {"iri://jobs/{job_id}", "iri://files{+path}"},
                str(template_uris),
            )

            job_resource = await session.read_resource(f"iri://jobs/{job_id}")
            job_json = job_resource.contents[0].text
            _check("job resource returns completed JSON", '"state": "completed"' in job_json, job_json)

            file_resource = await session.read_resource(f"iri://files{OUT}")
            file_text = file_resource.contents[0].text
            _check(
                "file resource reads the output file",
                "hello from the fake backend" in file_text,
                file_text,
            )

            print("SMOKE PASS")

    print("smoke client complete")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8971/api/v1")
    parser.add_argument("--allow-submit", action="store_true")
    parser.add_argument("--allow-fs-write", action="store_true")
    args = parser.parse_args()
    asyncio.run(
        run(args.base_url, args.allow_submit, args.allow_fs_write)
    )


if __name__ == "__main__":
    main()