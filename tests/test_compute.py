"""Compute tools: submit/run/list/get/wait/cancel, gates, caps, and tails."""

from __future__ import annotations

from typing import Any

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from helpers import SPEC, assert_tool_error, make_config, text_of

SUBMIT_TOOL = "submit_job"


async def _submit(server, **overrides: Any):
    spec: dict[str, Any] = {**SPEC, **overrides}
    return await server.call_tool(SUBMIT_TOOL, {"spec": spec})


async def test_submit_rejected_in_readonly_mode(make_server):
    server = make_server()  # default: readonly
    with pytest.raises(ToolError) as exc:
        await _submit(server)
    assert_tool_error(exc.value, "readonly", "--allow-submit")


async def test_submit_success(make_server):
    server = make_server(config=make_config(allow_submit=True))
    result = await _submit(server)
    sc = result.structured_content
    assert sc["job_id"] == "job-1"
    assert sc["state"] == "completed"
    assert sc["exit_code"] == 0
    assert sc["submitted"] is True
    assert sc["timed_out"] is False


async def test_submitted_body_contract(make_server, fake):
    server = make_server(config=make_config(allow_submit=True))
    await _submit(server)
    body = fake.bodies[0]
    assert body["name"] == SPEC["name"]
    assert body["executable"] == SPEC["executable"]
    assert body["arguments"] == SPEC["arguments"]
    assert body["directory"] == SPEC["directory"]
    assert body["stdout_path"] == SPEC["stdout_path"]
    assert body["stderr_path"] == SPEC["stderr_path"]
    assert body["attributes"] == {
        "account": "m0000",
        "queue_name": "debug",
        "duration": 60,
    }
    assert body["resources"]["node_count"] == 1
    assert body["resources"]["processes_per_node"] == 1


async def test_duration_cap_rejected(make_server):
    server = make_server(config=make_config(allow_submit=True, max_duration_sec=60))
    with pytest.raises(ToolError) as exc:
        await _submit(server, duration=61)
    assert_tool_error(exc.value, "duration", "61", "cap")


async def test_node_cap_rejected(make_server):
    server = make_server(config=make_config(allow_submit=True, max_nodes=1))
    with pytest.raises(ToolError) as exc:
        await _submit(server, node_count=2)
    assert_tool_error(exc.value, "node_count", "--max-nodes")


async def test_queue_allowlist_rejected(make_server):
    server = make_server(
        config=make_config(allow_submit=True, allowed_queues=("debug",))
    )
    with pytest.raises(ToolError) as exc:
        await _submit(server, queue_name="regular")
    assert_tool_error(exc.value, "queue 'regular'", "--allowed-queues")


async def test_run_job_returns_tails(make_server, fake):
    fake.files[SPEC["stdout_path"]] = "hello world\n"
    server = make_server(config=make_config(allow_submit=True))
    result = await server.call_tool(
        "run_job", {"spec": {**SPEC}, "timeout": 5.0}
    )
    sc = result.structured_content
    assert sc["job_id"] == "job-1"
    assert sc["state"] == "completed"
    assert sc["exit_code"] == 0
    assert sc["submitted"] is True
    assert sc["timed_out"] is False
    assert sc["timeout_sec"] == 5.0
    assert sc["stdout_tail"] == "hello world\n"
    assert sc["tails_capped"] is False


async def test_run_job_tail_capped_when_line_cap_small(make_server, fake):
    fake.files[SPEC["stdout_path"]] = "hello\n"
    server = make_server(config=make_config(allow_submit=True, max_lines=5))
    result = await server.call_tool("run_job", {"spec": {**SPEC}, "timeout": 5.0})
    sc = result.structured_content
    assert sc["tails_capped"] is True
    assert sc["stdout_tail"] == "hello\n"


async def test_run_job_tail_error_reported(make_server, fake):
    fake.errors.add(SPEC["stdout_path"])
    fake.files[SPEC["stdout_path"]] = "hello\n"
    server = make_server(config=make_config(allow_submit=True))
    result = await server.call_tool("run_job", {"spec": {**SPEC}, "timeout": 5.0})
    sc = result.structured_content
    assert sc["state"] == "completed"
    assert "stdout" in sc["tail_error"]
    assert sc["job_id"] == "job-1"


async def test_run_job_times_out_before_terminal(make_server, fake):
    fake.auto_complete = False
    server = make_server(config=make_config(allow_submit=True))
    result = await server.call_tool(
        "run_job", {"spec": {**SPEC}, "timeout": 0.05}
    )
    sc = result.structured_content
    assert sc["timed_out"] is True
    assert sc["state"] == "queued"
    assert sc["exit_code"] is None


async def test_list_jobs_filters_by_state(make_server, fake):
    fake.seed_job("job-a", state="completed", exit_code=0)
    fake.seed_job("job-b", state="failed", exit_code=1)
    server = make_server()
    result = await server.call_tool(
        "list_jobs", {"state": "completed", "limit": 5}
    )
    jobs = result.structured_content["result"]
    assert [j["job_id"] for j in jobs] == ["job-a"]
    assert jobs[0]["state"] == "completed"
    assert jobs[0]["exit_code"] == 0


async def test_list_jobs_filters_by_queue(make_server, fake):
    fake.seed_job(
        "job-q",
        state="failed",
        exit_code=1,
        job_spec={"attributes": {"queue_name": "regular"}},
    )
    server = make_server()
    result = await server.call_tool("list_jobs", {"queue": "regular"})
    jobs = result.structured_content["result"]
    assert [j["job_id"] for j in jobs] == ["job-q"]


async def test_get_job(make_server, fake):
    fake.seed_job("job-solo", state="queued")
    server = make_server()
    result = await server.call_tool("get_job", {"job_id": "job-solo"})
    sc = result.structured_content
    assert sc["job_id"] == "job-solo"
    assert sc["state"] == "queued"


async def test_wait_job_recovers_output_paths(make_server, fake):
    fake.seed_job(
        "job-w",
        state="completed",
        exit_code=0,
        job_spec={
            "stdout_path": "/out/a.log",
            "stderr_path": "/out/a.err",
        },
    )
    fake.files["/out/a.log"] = "done\n"
    server = make_server()
    result = await server.call_tool("wait_job", {"job_id": "job-w", "timeout": 5.0})
    sc = result.structured_content
    assert sc["state"] == "completed"
    assert sc["exit_code"] == 0
    assert sc["stdout_tail"] == "done\n"
    assert sc["timed_out"] is False


async def test_wait_job_times_out(make_server, fake):
    fake.seed_job("job-slow", state="queued")
    fake.auto_complete = False
    server = make_server()
    result = await server.call_tool("wait_job", {"job_id": "job-slow", "timeout": 0.05})
    sc = result.structured_content
    assert sc["timed_out"] is True
    assert sc["state"] == "queued"


async def test_cancel_job_rejected_in_readonly(make_server, fake):
    fake.seed_job("job-c", state="queued")
    server = make_server()
    with pytest.raises(ToolError) as exc:
        await server.call_tool("cancel_job", {"job_id": "job-c"})
    assert_tool_error(exc.value, "--allow-submit")
    assert fake.jobs["job-c"]["status"]["state"] == "queued"


async def test_cancel_job_success(make_server, fake):
    fake.seed_job("job-c", state="queued")
    server = make_server(config=make_config(allow_submit=True))
    result = await server.call_tool("cancel_job", {"job_id": "job-c"})
    assert "cancel request sent" in text_of(result)
    assert fake.jobs["job-c"]["status"]["state"] == "canceled"


async def test_compute_requires_credentials(make_server):
    server = make_server(access_token=None)
    with pytest.raises(ToolError) as exc:
        await server.call_tool("list_jobs", {})
    assert_tool_error(exc.value, "no credentials", "IRI_API_TOKEN")