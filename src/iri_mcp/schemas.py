"""Shared pydantic schemas for tool inputs and structured results."""

from __future__ import annotations

from pydantic import BaseModel, Field


class JobSpecInput(BaseModel):
    """Input schema mirroring the client ``JobSpec`` for the exposed subset.

    Only the fields an agent reasonably sets when running a job are exposed;
    container/environment/stdin/pre/post-launch options are out of scope.
    """

    name: str = Field(..., description="Short name for the job (e.g. 'my-sim').")
    executable: str = Field(
        ..., description="Absolute path to the executable or script to run."
    )
    account: str = Field(
        ...,
        description="Account/project to charge for resource usage. Never invent "
        "one; discover valid values via list_projects or ask the user.",
    )
    arguments: list[str] | None = Field(
        None, description="Command-line arguments passed to the executable."
    )
    directory: str | None = Field(
        None, description="Working directory for the job on the shared filesystem."
    )
    stdout_path: str | None = Field(
        None, description="Remote path to write standard output."
    )
    stderr_path: str | None = Field(
        None, description="Remote path to write standard error."
    )
    queue_name: str | None = Field(
        None,
        description="Queue/partition to submit to (e.g. 'debug'). Confirm the "
        "queue and its limits with the user or from facility docs.",
    )
    duration: int | None = Field(
        None,
        description="Requested wall-clock duration in seconds. Capped by the "
        "server's --max-duration-sec.",
    )
    node_count: int = Field(
        1,
        ge=1,
        description="Number of compute nodes to request. Capped by --max-nodes.",
    )
    processes_per_node: int = Field(
        1,
        ge=1,
        description="Number of processes to launch per node. Capped by "
        "--max-processes-per-node.",
    )


class JobResult(BaseModel):
    """Structured result returned by submit/get/wait/run tool family."""

    job_id: str = Field(..., description="IRI job id.")
    state: str | None = Field(
        None,
        description="Current job state: new|queued|held|active|completed|failed|canceled.",
    )
    exit_code: int | None = Field(
        None, description="Process exit code once the job has finished."
    )
    message: str | None = Field(None, description="Scheduler status message.")
    submitted: bool = Field(
        False, description="True for freshly submitted jobs."
    )
    timed_out: bool = Field(
        False,
        description="True when the wait exceeded the requested timeout before "
        "reaching a terminal state.",
    )
    timeout_sec: float | None = Field(
        None, description="The timeout applied to the wait, in seconds."
    )
    stdout_tail: str | None = Field(
        None,
        description="Capped tail of the job's stdout, when stdout_path was set.",
    )
    stderr_tail: str | None = Field(
        None,
        description="Capped tail of the job's stderr, when stderr_path was set.",
    )
    tails_capped: bool = Field(
        False,
        description="True when the server's line cap truncated the tails.",
    )
    tail_error: str | None = Field(
        None,
        description="Set when a tail could not be read (e.g. the file was not "
        "created). The job itself is unaffected.",
    )


__all__ = ["JobSpecInput", "JobResult"]