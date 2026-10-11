"""The ``conduct-scientific-workflow`` prompt: conventions for the assistant.

Copy is intentionally agent-harness agnostic: the caller is described only as
"the assistant" / "the agent".
"""

from __future__ import annotations

from mcp.server import MCPServer
from mcp.server.mcpserver import AssistantMessage, Message, UserMessage

WORKFLOW_DESCRIPTION = (
    "Conventions for running a scientific workflow on NERSC IRI through the "
    "available MCP tools: verify facility/resource status first, prefer short "
    "run_job scripts, read errors with fs_tail, never invent account/queue/"
    "duration, and verify outputs."
)

WORKFLOW_USER_TEXT = """\
You are assisting a scientist who will run a workflow on the NERSC IRI facility
through the MCP tools on this server. Follow these conventions:

1. Orient first. Call get_facility_info and get_resource_status before any
   compute or filesystem work, so the agent does not act on a down or
   misconfigured resource. Check get_incidents when status looks degraded.

2. Prefer short, self-contained jobs. Use run_job with tiny scripts (e.g.
   /bin/echo or a short shell command) to sanity-check execution, paths, and
   permissions before launching anything expensive. Redirect output to
   stdout_path / stderr_path so results are inspectable.

3. Read errors, do not guess. When a job fails, read its stderr via fs_tail
   (and stdout via fs_head / fs_tail) before retrying or escalating.

4. Never invent account, queue, or duration. Confirm these with the user; the
   account should be a real IRI project (list_projects can help the agent
   discover the ones it belongs to). Stay within the server's documented caps:
   it will reject requests that exceed them, cite the flag, and suggest the
   correct limit.

5. Verify outputs. Compare produced files against expected values where they
   are deterministic, and confirm integrity with fs_checksum. Check exit codes
   in run_job / wait_job results; a completed job with a non-zero exit code is
   not success.

6. Use unambiguous absolute paths on the shared filesystem, and clean up
   scratch files the tooling created when they are no longer needed.

7. Be honest about credentials. Observability and filesystem reads work in all
   modes; job submission and filesystem writes are only enabled when the server
   operator opted in. If a privileged call is rejected, tell the user what to
   restart the server with (--allow-submit, --allow-fs-write) and continue with
   whatever read-only work is still possible.

Report the final outcome, the commands the agent ran, the exit code, and the
checksums of the produced artifacts.
"""

WORKFLOW_ASSISTANT_TEXT = """\
Understood. I will orient with get_facility_info and get_resource_status first,
prefer short run_job checks, read failures with fs_tail, confirm account/queue/
duration with the user instead of inventing them, stay within the server caps,
and verify every produced artifact against expected values and checksums. I will
ask for the account/queue/duration and for any expected outputs I should verify.
"""


def register_prompt(mcp: MCPServer) -> None:
    """Register the scientific-workflow prompt on the server."""

    @mcp.prompt("conduct-scientific-workflow", description=WORKFLOW_DESCRIPTION)
    async def conduct_scientific_workflow(task: str | None = None) -> list[Message]:
        """Render the workflow conventions, optionally seeded with a task."""
        messages: list[Message] = [UserMessage(content=WORKFLOW_USER_TEXT)]
        if task:
            messages.append(
                UserMessage(
                    content=f"The scientist's workflow: {task}. Proceed per the conventions."
                )
            )
        messages.append(AssistantMessage(content=WORKFLOW_ASSISTANT_TEXT))
        return messages


__all__ = ["register_prompt", "WORKFLOW_DESCRIPTION"]