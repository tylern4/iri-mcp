"""Runner interface and the concrete ``IriRunner``.

``Runner`` is the thin interface (``submit`` / ``wait`` / ``read-file`` /
``checksum``) that the phase-2 evaluation harness drives without an MCP
transport. ``IriRunner`` implements it over the IRI client and also provides
every other tool operation, so the MCP tools are thin wrappers around the exact
same code paths — policy gates, caps, and audit included.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Any

from iri_client import AsyncClient, IriError
from iri_client._models import JobSpec, JobState, JobStatus

from .client import client_session
from .config import Config
from .safety import Policy
from .schemas import JobResult, JobSpecInput

# Terminal job states (note the single-"l" IRI spelling of "canceled").
TERMINAL_JOB_STATES = frozenset(
    {JobState.completed, JobState.failed, JobState.canceled}
)
# Default number of tail lines for run_job/wait_job, clamped by --max-lines.
TAIL_LINES = 50

ClientFactory = Callable[[], AbstractAsyncContextManager[AsyncClient]]


def _default_client_factory(config: Config) -> ClientFactory:
    def factory() -> AbstractAsyncContextManager[AsyncClient]:
        return client_session(config)

    return factory


def _to_job_spec(spec: JobSpecInput) -> JobSpec:
    """Coerce the tool input schema to the client's ``JobSpec``."""
    attributes: dict[str, Any] = {"account": spec.account}
    if spec.queue_name is not None:
        attributes["queue_name"] = spec.queue_name
    if spec.duration is not None:
        attributes["duration"] = spec.duration

    resources: dict[str, Any] = {}
    if spec.node_count is not None:
        resources["node_count"] = spec.node_count
    if spec.processes_per_node is not None:
        resources["processes_per_node"] = spec.processes_per_node

    payload: dict[str, Any] = {
        "name": spec.name,
        "executable": spec.executable,
        "attributes": attributes,
    }
    if spec.arguments is not None:
        payload["arguments"] = spec.arguments
    if spec.directory is not None:
        payload["directory"] = spec.directory
    if spec.stdout_path is not None:
        payload["stdout_path"] = spec.stdout_path
    if spec.stderr_path is not None:
        payload["stderr_path"] = spec.stderr_path
    if resources:
        payload["resources"] = resources
    return JobSpec(**payload)


def _job_result(job_id: str, status: JobStatus | None = None, **kwargs: Any) -> JobResult:
    state: str | None = None
    exit_code: int | None = None
    message: str | None = None
    if status is not None:
        state = status.state.value if isinstance(status.state, JobState) else status.state
        exit_code = status.exit_code
        message = status.message
    return JobResult(
        job_id=job_id, state=state, exit_code=exit_code, message=message, **kwargs
    )


class Runner(ABC):
    """Code paths the evaluation harness reuses without an MCP transport."""

    @abstractmethod
    async def submit(self, spec: JobSpecInput) -> JobResult:
        """Submit a job and return its initial result."""

    @abstractmethod
    async def wait(self, job_id: str, timeout: float | None = None) -> JobResult:
        """Poll a job until a terminal state, a timeout, or ``timeout=None`` forever."""

    @abstractmethod
    async def read_file(self, path: str, max_bytes: int | None = None) -> str:
        """Read a small text file as a string, capped at ``max_bytes``."""

    @abstractmethod
    async def checksum(self, path: str) -> str:
        """Return the SHA-256 checksum of a remote file."""


class IriRunner(Runner):
    """Thin, gate-aware implementation over ``AsyncClient``."""

    def __init__(
        self,
        config: Config,
        client_factory: ClientFactory | None = None,
        policy: Policy | None = None,
    ):
        self._config = config
        self.policy = policy if policy is not None else Policy.from_config(config)
        self._client_factory = client_factory or _default_client_factory(config)

    # ------------------------------------------------------------------
    # Observability
    # ------------------------------------------------------------------

    async def facility_info(self) -> dict[str, Any]:
        async with self._client_factory() as client:
            info = await client.facility.info()
        return info.model_dump(mode="json")

    async def facility_sites(self) -> list[dict[str, Any]]:
        async with self._client_factory() as client:
            sites = await client.facility.sites()
        return [site.model_dump(mode="json") for site in sites]

    async def resource_status(self) -> dict[str, Any]:
        async with self._client_factory() as client:
            resources = await client.status.resources()
            statuses = await client.status.statuses()
        return {
            "resources": [r.model_dump(mode="json") for r in resources],
            "statuses": statuses,
        }

    async def incidents(self) -> list[dict[str, Any]]:
        async with self._client_factory() as client:
            incidents = await client.status.incidents()
        return [i.model_dump(mode="json") for i in incidents]

    async def projects(self) -> list[dict[str, Any]]:
        async with self._client_factory() as client:
            projects = await client.account.projects()
        return [p.model_dump(mode="json") for p in projects]

    # ------------------------------------------------------------------
    # Compute
    # ------------------------------------------------------------------

    async def submit(self, spec: JobSpecInput) -> JobResult:
        self._gate_submit("submit_job", spec)
        async with self._client_factory() as client:
            compute = await client.compute(self._config.compute_resource)
            job = await compute.submit(_to_job_spec(spec))
            status = await job.status
        return _job_result(job.id, status, submitted=True)

    async def run_job(self, spec: JobSpecInput, timeout: float = 600.0) -> JobResult:
        self._gate_submit("run_job", spec)
        async with self._client_factory() as client:
            compute = await client.compute(self._config.compute_resource)
            job = await compute.submit(_to_job_spec(spec))
            status, timed_out = await self._await_status(client, compute, job.id, timeout)
            stdout_tail, stderr_tail, tails_capped, tail_error = await self._read_tails(
                client, spec.stdout_path, spec.stderr_path
            )
        return _job_result(
            job.id,
            status,
            submitted=True,
            timed_out=timed_out,
            timeout_sec=timeout,
            stdout_tail=stdout_tail,
            stderr_tail=stderr_tail,
            tails_capped=tails_capped,
            tail_error=tail_error,
        )

    async def wait(self, job_id: str, timeout: float | None = None) -> JobResult:
        async with self._client_factory() as client:
            compute = await client.compute(self._config.compute_resource)
            status, timed_out = await self._await_status(client, compute, job_id, timeout)
            stdout_path, stderr_path = await self._spec_paths(client, compute, job_id)
            stdout_tail, stderr_tail, tails_capped, tail_error = await self._read_tails(
                client, stdout_path, stderr_path
            )
        return _job_result(
            job_id,
            status,
            timed_out=timed_out,
            timeout_sec=timeout,
            stdout_tail=stdout_tail,
            stderr_tail=stderr_tail,
            tails_capped=tails_capped,
            tail_error=tail_error,
        )

    async def get_job(self, job_id: str) -> JobResult:
        async with self._client_factory() as client:
            compute = await client.compute(self._config.compute_resource)
            job = await compute.job(job_id)
            status = await job.status
        return _job_result(job_id, status)

    async def list_jobs(
        self,
        state: JobState | None = None,
        queue: str | None = None,
        limit: int = 50,
    ) -> list[JobResult]:
        filters: dict[str, str] = {}
        if state is not None:
            filters["state"] = state.value
        if queue is not None:
            filters["queue_name"] = queue
        async with self._client_factory() as client:
            compute = await client.compute(self._config.compute_resource)
            jobs = await compute.list(filters=filters, limit=limit)
            results: list[JobResult] = []
            for job in jobs:
                status = await job.status
                results.append(_job_result(job.id, status))
        return results

    async def cancel(self, job_id: str) -> str:
        self.policy.require_submit(tool="cancel_job")
        self.policy.audit(tool="cancel_job", allowed=True, job_id=job_id)
        async with self._client_factory() as client:
            compute = await client.compute(self._config.compute_resource)
            job = await compute.job(job_id)
            await job.cancel()
        return f"cancel request sent for job {job_id}"

    # ------------------------------------------------------------------
    # Filesystem
    # ------------------------------------------------------------------

    async def fs_list(self, path: str, limit: int = 50) -> list[dict[str, Any]]:
        async with self._client_factory() as client:
            fs = await client.filesystem(self._config.filesystem_resource)
            entries = await fs.list(path)
        return list(entries[: max(0, int(limit))])

    async def fs_head(self, path: str, lines: int = 10) -> str:
        bounded = self.policy.cap_lines(lines)
        async with self._client_factory() as client:
            fs = await client.filesystem(self._config.filesystem_resource)
            return await fs.head(path, lines=bounded)

    async def fs_tail(self, path: str, lines: int = 10) -> str:
        bounded = self.policy.cap_lines(lines)
        async with self._client_factory() as client:
            fs = await client.filesystem(self._config.filesystem_resource)
            return await fs.tail(path, lines=bounded)

    async def fs_stat(self, path: str) -> dict[str, Any]:
        async with self._client_factory() as client:
            fs = await client.filesystem(self._config.filesystem_resource)
            return await fs.stat(path)

    async def checksum(self, path: str) -> str:
        async with self._client_factory() as client:
            fs = await client.filesystem(self._config.filesystem_resource)
            return await fs.checksum(path)

    async def read_file(self, path: str, max_bytes: int | None = None) -> str:
        bounded = self.policy.cap_read_bytes(max_bytes)
        async with self._client_factory() as client:
            fs = await client.filesystem(self._config.filesystem_resource)
            return await fs.head(path, bytes_=bounded)

    async def fs_write_text(self, path: str, content: str) -> str:
        self.policy.require_fs_write(tool="fs_write_text")
        raw = content.encode("utf-8")
        self.policy.check_write_bytes(len(raw))
        self.policy.audit(
            tool="fs_write_text", allowed=True, path=path, bytes=len(raw)
        )
        handle, tmp = tempfile.mkstemp(prefix="iri_mcp_upload_", suffix=".txt")
        try:
            with os.fdopen(handle, "wb") as fh:
                fh.write(raw)
            async with self._client_factory() as client:
                fs = await client.filesystem(self._config.filesystem_resource)
                await fs.upload(tmp, path)
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        return f"wrote {len(raw)} bytes to {path}"

    async def fs_mkdir(self, path: str, parent: bool = True) -> str:
        self._gate_fs_write("fs_mkdir", path=path)
        async with self._client_factory() as client:
            fs = await client.filesystem(self._config.filesystem_resource)
            await fs.mkdir(path, parent=parent)
        return f"mkdir: created {path}"

    async def fs_copy(self, path: str, target_path: str) -> str:
        self._gate_fs_write("fs_copy", path=path, target_path=target_path)
        async with self._client_factory() as client:
            fs = await client.filesystem(self._config.filesystem_resource)
            await fs.copy(path, target_path)
        return f"copied {path} -> {target_path}"

    async def fs_move(self, path: str, target_path: str) -> str:
        self._gate_fs_write("fs_move", path=path, target_path=target_path)
        async with self._client_factory() as client:
            fs = await client.filesystem(self._config.filesystem_resource)
            await fs.move(path, target_path)
        return f"moved {path} -> {target_path}"

    async def fs_remove(self, path: str) -> str:
        self._gate_fs_write("fs_remove", path=path)
        async with self._client_factory() as client:
            fs = await client.filesystem(self._config.filesystem_resource)
            await fs.rm(path)
        return f"removed {path}"

    async def fs_symlink(self, path: str, link_path: str) -> str:
        self._gate_fs_write("fs_symlink", path=path, link_path=link_path)
        async with self._client_factory() as client:
            fs = await client.filesystem(self._config.filesystem_resource)
            await fs.symlink(path, link_path)
        return f"symlink {link_path} -> {path}"

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _gate_submit(self, tool: str, spec: JobSpecInput) -> None:
        self.policy.require_submit(tool=tool)
        caps = self.policy.check_job(spec)
        self.policy.audit(tool=tool, allowed=True, account=spec.account, caps=caps)

    def _gate_fs_write(self, tool: str, **fields: Any) -> None:
        self.policy.require_fs_write(tool=tool)
        self.policy.audit(tool=tool, allowed=True, **fields)

    async def _await_status(
        self,
        client: AsyncClient,
        compute: Any,
        job_id: str,
        timeout: float | None,
    ) -> tuple[JobStatus, bool]:
        """Poll job status until terminal, a timeout, or forever (timeout=None)."""
        job = await compute.job(job_id)
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            status = await job.status
            if status.state in TERMINAL_JOB_STATES:
                return status, False
            if deadline is not None and time.monotonic() >= deadline:
                return status, True
            await asyncio.sleep(self._config.wait_interval)

    async def _job_doc(self, client: AsyncClient, compute: Any, job_id: str) -> dict[str, Any]:
        """Fetch the full job document (status + job_spec) from the API."""
        response = await client.get(
            f"compute/status/{compute.id}/{job_id}", params={"include_spec": True}
        )
        return response.json()

    async def _spec_paths(
        self, client: AsyncClient, compute: Any, job_id: str
    ) -> tuple[str | None, str | None]:
        """Recover the stdout/stderr paths from the job document when available."""
        try:
            data = await self._job_doc(client, compute, job_id)
        except IriError:
            return None, None
        spec = data.get("job_spec") or {}
        return spec.get("stdout_path"), spec.get("stderr_path")

    async def _read_tails(
        self, client: AsyncClient, stdout_path: str | None, stderr_path: str | None
    ) -> tuple[str | None, str | None, bool, str | None]:
        if not stdout_path and not stderr_path:
            return None, None, False, None
        requested = TAIL_LINES
        lines = self.policy.cap_lines(requested)
        tails_capped = lines < requested
        fs = await client.filesystem(self._config.filesystem_resource)
        stdout_tail = stderr_tail = None
        tail_error: str | None = None
        if stdout_path:
            try:
                stdout_tail = await fs.tail(stdout_path, lines=lines)
            except IriError as exc:
                tail_error = tail_error or f"stdout: {exc}"
        if stderr_path:
            try:
                stderr_tail = await fs.tail(stderr_path, lines=lines)
            except IriError as exc:
                tail_error = tail_error or f"stderr: {exc}"
        return stdout_tail, stderr_tail, tails_capped, tail_error


__all__ = ["Runner", "IriRunner", "ClientFactory"]