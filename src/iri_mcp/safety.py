"""Safety gate: the single ``Policy`` every tool consults.

Enforces the mode gates (read-only by default; submit and fs-write are explicit
opt-ins) and the caps table from PLAN.md §3.2. Also owns the audit log: every
privileged call and every policy denial is recorded as a JSON line to
``--audit-file`` or stderr — never stdout.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

from .config import Config
from .schemas import JobSpecInput

_AUDIT_LOGGER_NAME = "iri_mcp.audit"


class PolicyError(Exception):
    """A tool call was denied by the safety policy gate or a cap."""


class AuditLog:
    """Best-effort JSONL audit sink (stderr by default, file when configured)."""

    def __init__(self, path: str | None = None):
        self._path = Path(path).expanduser() if path else None
        self._logger = logging.getLogger(_AUDIT_LOGGER_NAME)
        self._logger.propagate = False
        if not self._logger.handlers:
            handler = logging.StreamHandler(sys.stderr)
            handler.setFormatter(
                logging.Formatter("iri_mcp.audit | %(message)s")
            )
            self._logger.addHandler(handler)
        self._logger.setLevel(logging.INFO)
        if self._path is not None:
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
            except OSError:
                pass

    def record(self, event: dict[str, Any]) -> None:
        line = json.dumps(event, default=str, sort_keys=True)
        if self._path is not None:
            try:
                with self._path.open("a") as handle:
                    handle.write(line + "\n")
            except OSError as exc:
                self._logger.error("audit write failed: %s", exc)
        else:
            self._logger.info("AUDIT %s", line)


class Policy:
    """The single policy gate: mode + caps + audit."""

    def __init__(
        self,
        *,
        readonly: bool,
        allow_submit: bool,
        allow_fs_write: bool,
        max_duration_sec: int | None,
        max_nodes: int | None,
        max_processes_per_node: int | None,
        max_read_bytes: int,
        max_lines: int,
        max_write_bytes: int,
        allowed_queues: tuple | None,
        audit: AuditLog,
    ):
        self.readonly = readonly
        self.allow_submit = allow_submit
        self.allow_fs_write = allow_fs_write
        self.max_duration_sec = max_duration_sec
        self.max_nodes = max_nodes
        self.max_processes_per_node = max_processes_per_node
        self.max_read_bytes = max_read_bytes
        self.max_lines = max_lines
        self.max_write_bytes = max_write_bytes
        self.allowed_queues = allowed_queues
        self._audit = audit

    @classmethod
    def from_config(cls, config: Config) -> Policy:
        return cls(
            readonly=config.readonly,
            allow_submit=config.submit_enabled,
            allow_fs_write=config.fs_write_enabled,
            max_duration_sec=config.max_duration_sec,
            max_nodes=config.max_nodes,
            max_processes_per_node=config.max_processes_per_node,
            max_read_bytes=config.max_read_bytes,
            max_lines=config.max_lines,
            max_write_bytes=config.max_write_bytes,
            allowed_queues=config.allowed_queues,
            audit=AuditLog(config.audit_file),
        )

    # -- mode gates --------------------------------------------------------

    def require_submit(self, tool: str = "unknown") -> None:
        """Deny with an actionable message unless submit is enabled."""
        if self.readonly:
            self._deny(
                tool,
                "submission disabled: server is in readonly mode; restart with "
                "--allow-submit (and --allow-fs-write for file writes)",
            )
        if not self.allow_submit:
            self._deny(
                tool,
                "submission disabled: start with --allow-submit (or set "
                "IRI_MCP_ALLOW_SUBMIT=1)",
            )

    def require_fs_write(self, tool: str = "unknown") -> None:
        """Deny with an actionable message unless fs-write is enabled."""
        if self.readonly:
            self._deny(
                tool,
                "filesystem writes disabled: server is in readonly mode; restart "
                "with --allow-fs-write (and --allow-submit for jobs)",
            )
        if not self.allow_fs_write:
            self._deny(
                tool,
                "filesystem writes disabled: start with --allow-fs-write (or set "
                "IRI_MCP_ALLOW_FS_WRITE=1)",
            )

    # -- job caps ----------------------------------------------------------

    def check_job(self, spec: JobSpecInput) -> dict[str, Any]:
        """Reject a job spec that exceeds any cap; return the caps applied."""
        caps: dict[str, Any] = {}
        if (
            self.max_duration_sec is not None
            and spec.duration is not None
            and spec.duration > self.max_duration_sec
        ):
            raise PolicyError(
                f"job duration {spec.duration}s exceeds the {self.max_duration_sec}s "
                "cap (--max-duration-sec)"
            )
        caps["duration"] = spec.duration
        if (
            self.max_nodes is not None
            and spec.node_count is not None
            and spec.node_count > self.max_nodes
        ):
            raise PolicyError(
                f"node_count {spec.node_count} exceeds the {self.max_nodes}-node cap "
                "(--max-nodes)"
            )
        caps["node_count"] = spec.node_count
        if (
            self.max_processes_per_node is not None
            and spec.processes_per_node is not None
            and spec.processes_per_node > self.max_processes_per_node
        ):
            raise PolicyError(
                f"processes_per_node {spec.processes_per_node} exceeds the "
                f"{self.max_processes_per_node}-process cap (--max-processes-per-node)"
            )
        caps["processes_per_node"] = spec.processes_per_node
        if self.allowed_queues and spec.queue_name not in self.allowed_queues:
            raise PolicyError(
                f"queue '{spec.queue_name}' is not allowed; allowed queues: "
                f"{', '.join(self.allowed_queues)} (--allowed-queues)"
            )
        caps["queue_name"] = spec.queue_name
        return caps

    # -- read caps (clamp) -------------------------------------------------

    def cap_read_bytes(self, requested: int | None) -> int:
        """Clamp a requested read size to the byte cap."""
        target = self.max_read_bytes if requested is None else requested
        return max(0, min(int(target), self.max_read_bytes))

    def cap_lines(self, requested: int | None) -> int:
        """Clamp a requested line count to the line cap."""
        target = self.max_lines if requested is None else requested
        return max(1, min(int(target), self.max_lines))

    # -- write cap (reject) ------------------------------------------------

    def check_write_bytes(self, nbytes: int) -> None:
        """Reject content larger than the write cap."""
        if nbytes > self.max_write_bytes:
            raise PolicyError(
                f"content is {nbytes} bytes, exceeding the {self.max_write_bytes}-byte "
                "write cap (--max-write-bytes)"
            )

    # -- audit -------------------------------------------------------------

    def audit(self, *, tool: str, allowed: bool, account: str | None = None, **fields: Any) -> None:
        """Record one audit event (timestamp, tool, account, caps/fields)."""
        event: dict[str, Any] = {
            "ts": time.time(),
            "tool": tool,
            "allowed": allowed,
            "account": account,
        }
        event.update(fields)
        self._audit.record(event)

    def _deny(self, tool: str, message: str) -> None:
        self.audit(tool=tool, allowed=False, reason=message)
        raise PolicyError(message)


__all__ = ["Policy", "PolicyError", "AuditLog"]