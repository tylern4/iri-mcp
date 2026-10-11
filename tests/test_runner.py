"""Runner unit tests: the thin phase-2 interface over the fake IRI API."""

from __future__ import annotations

from typing import Any

import pytest

from helpers import SPEC
from iri_mcp.runner import Runner, _job_result, _to_job_spec
from iri_mcp.safety import PolicyError
from iri_mcp.schemas import JobSpecInput


def _spec(**over: Any) -> JobSpecInput:
    base: dict[str, Any] = {**SPEC, **over}
    return JobSpecInput(**base)


def test_runner_is_abstract():
    with pytest.raises(TypeError):
        Runner()  # type: ignore[abstract]


async def test_submit_returns_initial_result(make_runner):
    runner = make_runner(allow_submit=True)
    result = await runner.submit(_spec())
    assert result.job_id == "job-1"
    assert result.submitted is True
    assert result.state == "completed"
    assert result.exit_code == 0


async def test_submit_denied_in_readonly(make_runner):
    runner = make_runner()
    with pytest.raises(PolicyError, match="--allow-submit"):
        await runner.submit(_spec())


async def test_run_job_returns_tails(make_runner, fake):
    fake.files[SPEC["stdout_path"]] = "hello\n"
    runner = make_runner(allow_submit=True)
    result = await runner.run_job(_spec(), timeout=5.0)
    assert result.stdout_tail == "hello\n"
    assert result.exit_code == 0
    assert result.submitted is True


async def test_run_job_denied_in_readonly(make_runner):
    runner = make_runner()
    with pytest.raises(PolicyError, match="--allow-submit"):
        await runner.run_job(_spec(), timeout=5.0)


async def test_wait_times_out(make_runner, fake):
    fake.seed_job("job-slow", state="queued")
    fake.auto_complete = False
    runner = make_runner()
    result = await runner.wait("job-slow", timeout=0.05)
    assert result.timed_out is True
    assert result.state == "queued"


async def test_wait_terminal_with_recovered_tails(make_runner, fake):
    fake.seed_job(
        "job-w",
        state="completed",
        exit_code=0,
        job_spec={"stdout_path": "/o.log", "stderr_path": "/e.log"},
    )
    fake.files["/o.log"] = "done\n"
    runner = make_runner()
    result = await runner.wait("job-w", timeout=5.0)
    assert result.state == "completed"
    assert result.stdout_tail == "done\n"
    assert result.timed_out is False


async def test_get_job(make_runner, fake):
    fake.seed_job("job-g", state="queued")
    runner = make_runner()
    result = await runner.get_job("job-g")
    assert result.job_id == "job-g"
    assert result.state == "queued"


async def test_list_jobs(make_runner, fake):
    fake.seed_job("job-a", state="completed", exit_code=0)
    fake.seed_job("job-b", state="failed", exit_code=1)
    runner = make_runner()
    results = await runner.list_jobs(state=None, queue=None, limit=10)
    assert {r.job_id for r in results} == {"job-a", "job-b"}


async def test_cancel_gated(make_runner, fake):
    fake.seed_job("job-c", state="queued")
    runner = make_runner()
    with pytest.raises(PolicyError, match="--allow-submit"):
        await runner.cancel("job-c")


async def test_cancel_success(make_runner, fake):
    fake.seed_job("job-c", state="queued")
    runner = make_runner(allow_submit=True)
    message = await runner.cancel("job-c")
    assert "cancel request sent" in message
    assert fake.jobs["job-c"]["status"]["state"] == "canceled"


async def test_read_file_clamped(make_runner, fake):
    fake.files["/x"] = "0123456789"
    runner = make_runner(max_read_bytes=64)
    content = await runner.read_file("/x", max_bytes=1000)
    assert content == "0123456789"
    head_params = [
        params
        for method, key, params in fake.param_calls
        if method == "GET" and key.startswith("filesystem/head")
    ]
    assert head_params and all(p["bytes"] == "64" for p in head_params)


async def test_checksum(make_runner, fake):
    fake.checksums["/x"] = "dd" * 32
    runner = make_runner()
    assert await runner.checksum("/x") == "dd" * 32


async def test_fs_write_text_gated(make_runner):
    runner = make_runner()
    with pytest.raises(PolicyError, match="--allow-fs-write"):
        await runner.fs_write_text("/x", "hi")


async def test_fs_write_text_success(make_runner, fake):
    runner = make_runner(allow_fs_write=True)
    message = await runner.fs_write_text("/x", "hello")
    assert message == "wrote 5 bytes to /x"
    assert any(key.startswith("filesystem/upload") for _, key in fake.calls)


async def test_fs_write_text_over_cap(make_runner, fake):
    runner = make_runner(allow_fs_write=True, max_write_bytes=4)
    with pytest.raises(PolicyError, match="write cap"):
        await runner.fs_write_text("/x", "hello")


def test_to_job_spec_maps_input_to_client_spec():
    spec = _spec()
    jobspec = _to_job_spec(spec)
    assert jobspec.name == SPEC["name"]
    assert jobspec.executable == SPEC["executable"]
    assert jobspec.arguments == SPEC["arguments"]
    assert jobspec.directory == SPEC["directory"]
    assert jobspec.stdout_path == SPEC["stdout_path"]
    assert jobspec.attributes.account == "m0000"
    assert jobspec.attributes.queue_name == "debug"
    assert jobspec.attributes.duration == 60
    assert jobspec.resources.node_count == 1
    assert jobspec.resources.processes_per_node == 1


def test_to_job_spec_omits_unset_attributes():
    jobspec = _to_job_spec(_spec(queue_name=None, duration=None))
    assert jobspec.attributes.account == "m0000"
    assert jobspec.attributes.queue_name is None
    assert jobspec.attributes.duration is None
    assert jobspec.resources.node_count == 1
    assert jobspec.resources.processes_per_node == 1


def test_job_result_maps_state():
    from iri_client._models import JobStatus

    status = JobStatus.model_validate(
        {"state": "failed", "exit_code": 2, "message": "bad luck"}
    )
    result = _job_result("job-x", status)
    assert result.state == "failed"
    assert result.exit_code == 2
    assert result.submitted is False


async def test_fs_list_and_stat(make_runner, fake):
    fake.seed_dir("/d", [{"name": "a", "type": "file"}])
    fake.files["/d/a"] = "abcd"
    runner = make_runner()
    entries = await runner.fs_list("/d")
    assert entries[0]["name"] == "a"
    stat = await runner.fs_stat("/d/a")
    assert stat["size"] == 4