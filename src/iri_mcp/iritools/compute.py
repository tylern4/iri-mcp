"""Compute tools: submit/run/list/get/wait/cancel jobs.

Submit, run, and cancel require the server to be started with ``--allow-submit``.
"""

from __future__ import annotations

from iri_client._models import JobState
from mcp.server import MCPServer

from ..errors import iri_tool
from ..runner import Runner
from ..schemas import JobResult, JobSpecInput


def register(mcp: MCPServer, runner: Runner) -> None:
    """Register the compute tool family."""

    @mcp.tool()
    @iri_tool
    async def submit_job(spec: JobSpecInput) -> JobResult:
        """Submit a job to the IRI compute resource.

        Requires the server to be running with ``--allow-submit``. The assistant
        must supply a valid ``account`` (see ``list_projects`` or ask the user)
        and stay within the server caps on duration, node count, and queue.
        Returns the initial job status; poll to completion with ``wait_job``, or
        use ``run_job`` for a one-shot submit-and-wait.
        """
        return await runner.submit(spec)

    @mcp.tool()
    @iri_tool
    async def run_job(spec: JobSpecInput, timeout: float = 600.0) -> JobResult:
        """Submit a job and wait up to ``timeout`` seconds for it to finish.

        Requires ``--allow-submit``. Returns the terminal state, exit code, and
        the last (capped) lines of stdout/stderr when ``stdout_path`` /
        ``stderr_path`` are set. If the timeout passes before a terminal state
        the result carries ``timed_out=true`` with the current state so the
        assistant can decide whether to poll or cancel.
        """
        return await runner.run_job(spec, timeout=timeout)

    @mcp.tool()
    @iri_tool
    async def list_jobs(
        state: JobState | None = None,
        queue: str | None = None,
        limit: int = 50,
    ) -> list[JobResult]:
        """List jobs on the IRI compute resource.

        Optionally filter by ``state`` (new, queued, held, active, completed,
        failed, canceled) and by ``queue``; cap the number returned with
        ``limit``. Requires credentials.
        """
        return await runner.list_jobs(state, queue, limit)

    @mcp.tool()
    @iri_tool
    async def get_job(job_id: str) -> JobResult:
        """Fetch the current status of a single job by id. Requires credentials."""
        return await runner.get_job(job_id)

    @mcp.tool()
    @iri_tool
    async def wait_job(job_id: str, timeout: float = 600.0) -> JobResult:
        """Wait until job ``job_id`` reaches a terminal state (up to ``timeout``
        seconds) and return its status, exit code, and capped output tails.

        Requires credentials. ``timed_out`` distinguishes a timeout from a
        terminal failure so the assistant can decide what to do next.
        """
        return await runner.wait(job_id, timeout=timeout)

    @mcp.tool()
    @iri_tool
    async def cancel_job(job_id: str) -> str:
        """Request cancellation of a job by id. Requires ``--allow-submit``."""
        return await runner.cancel(job_id)


__all__ = ["register"]