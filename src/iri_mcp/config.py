"""Server configuration.

Precedence is ``CLI flags > environment > defaults``. Environment variables are
prefixed ``IRI_MCP_`` (see PLAN.md §6 for the full table).
"""

from __future__ import annotations

import argparse
import os
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

from .facilities import (
    DEFAULT_FACILITY,
    FACILITIES,
    Facility,
    facility_for,
    resolve_token,
)

ENV_PREFIX = "IRI_MCP_"
DEFAULT_API_BASE_URL = FACILITIES[DEFAULT_FACILITY].base_url

_TRUTHY = {"1", "true", "yes", "on"}


def _to_bool(value: Any, default: bool = False) -> bool:
    """Parse a config value as a boolean, with ``default`` for ``None``."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in _TRUTHY


class Config(BaseModel):
    """Immutable server configuration."""

    model_config = ConfigDict(frozen=True)

    # Facility selection (NERSC | ALCF | ESnet); fills base URL + resource
    # defaults unless overridden explicitly.
    facility: str = DEFAULT_FACILITY

    # Transport / server
    api_base_url: str = DEFAULT_API_BASE_URL
    transport: str = "stdio"
    host: str = "127.0.0.1"
    port: int = 8000
    log_level: str = "INFO"

    # Privilege gates (explicit opt-ins; read-only by default)
    readonly_explicit: bool = False
    allow_submit: bool = False
    allow_fs_write: bool = False

    # Caps (see PLAN.md §3.2 for reject-vs-clamp semantics)
    max_duration_sec: int | None = 3600
    max_nodes: int | None = 8
    max_processes_per_node: int | None = 256
    max_read_bytes: int = 65536
    max_lines: int = 1000
    max_write_bytes: int = 1_048_576
    allowed_queues: tuple[str, ...] | None = None

    # IRI bindings
    compute_resource: str = "jobs"
    filesystem_resource: str = "scratch"
    wait_interval: float = 10.0
    audit_file: str | None = None

    @property
    def readonly(self) -> bool:
        """True when no privileged surface is enabled."""
        return self.readonly_explicit or not (self.allow_submit or self.allow_fs_write)

    @property
    def submit_enabled(self) -> bool:
        """Job submission is allowed only without an explicit readonly override."""
        return (not self.readonly_explicit) and self.allow_submit

    @property
    def fs_write_enabled(self) -> bool:
        return (not self.readonly_explicit) and self.allow_fs_write

    @property
    def profile(self) -> Facility:
        """The :class:`Facility` bindings for the selected ``facility``."""
        return facility_for(self.facility)

    @property
    def compute_discovery(self) -> str:
        """Resource-discovery strategy for compute (``router`` or ``status``)."""
        return self.profile.compute_discovery

    @property
    def filesystem_discovery(self) -> str:
        """Resource-discovery strategy for filesystems (``router``/``status``)."""
        return self.profile.filesystem_discovery

    def resolve_token(self, environ: Mapping[str, str] | None = None) -> str | None:
        """Resolve a bearer token for the configured facility (env, then file)."""
        return resolve_token(self.profile, environ)

    @field_validator("facility")
    @classmethod
    def _check_facility(cls, value: str) -> str:
        return facility_for(value).key

    @field_validator("transport")
    @classmethod
    def _check_transport(cls, value: str) -> str:
        if value not in ("stdio", "streamable-http"):
            raise ValueError("transport must be 'stdio' or 'streamable-http'")
        return value

    @classmethod
    def load(
        cls,
        argv: Sequence[str] | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> Config:
        """Build config from CLI args with environment fallbacks."""
        env = dict(os.environ if environ is None else environ)

        parser = argparse.ArgumentParser(
            prog="iri-mcp",
            description=(
                "MCP server for the NERSC, ALCF, and ESnet IRI Facility APIs."
            ),
        )
        parser.add_argument("--facility", choices=sorted(FACILITIES), default=None)
        parser.add_argument("--api-base-url", default=None)
        parser.add_argument(
            "--transport", choices=["stdio", "streamable-http"], default=None
        )
        parser.add_argument("--host", default=None)
        parser.add_argument("--port", type=int, default=None)
        parser.add_argument("--log-level", default=None)

        parser.add_argument("--readonly", action="store_true", default=None)
        parser.add_argument("--allow-submit", action="store_true", default=None)
        parser.add_argument("--allow-fs-write", action="store_true", default=None)

        parser.add_argument("--max-duration-sec", type=int, default=None)
        parser.add_argument("--max-nodes", type=int, default=None)
        parser.add_argument("--max-processes-per-node", type=int, default=None)
        parser.add_argument("--max-read-bytes", type=int, default=None)
        parser.add_argument("--max-lines", type=int, default=None)
        parser.add_argument("--max-write-bytes", type=int, default=None)
        parser.add_argument("--allowed-queues", action="append", default=None)
        parser.add_argument("--audit-file", default=None)
        parser.add_argument("--compute-resource", default=None)
        parser.add_argument("--filesystem-resource", default=None)
        parser.add_argument("--wait-interval", type=float, default=None)

        args = parser.parse_args(list(argv) if argv is not None else None)

        def pick(flag: Any, name: str, default: Any) -> Any:
            """CLI value, else env value, else default."""
            if flag is not None:
                return flag
            if name in env and env[name] not in ("",):
                return env[name]
            return default

        def pick_int(flag: Any, name: str, default: int | None) -> int | None:
            raw = pick(flag, name, default)
            return None if raw is None else int(raw)

        def pick_bool(flag: Any, name: str, default: bool = False) -> bool:
            if flag is not None:
                return bool(flag)
            return _to_bool(env.get(name), default=default)

        allowed_raw = pick(args.allowed_queues, "IRI_MCP_ALLOWED_QUEUES", None)
        allowed_queues: tuple[str, ...] | None = None
        if allowed_raw:
            parts: list[str] = []
            values: list[Any] = (
                list(allowed_raw) if isinstance(allowed_raw, list) else [allowed_raw]
            )
            for value in values:
                parts.extend(
                    piece.strip() for piece in str(value).split(",") if piece.strip()
                )
            allowed_queues = tuple(sorted(set(parts))) or None

        facility_raw = str(pick(args.facility, "IRI_MCP_FACILITY", DEFAULT_FACILITY))
        profile = facility_for(facility_raw)

        return cls(
            facility=profile.key,
            api_base_url=str(
                pick(args.api_base_url, "IRI_MCP_API_BASE_URL", profile.base_url)
            ),
            transport=str(pick(args.transport, "IRI_MCP_TRANSPORT", "stdio")),
            host=str(pick(args.host, "IRI_MCP_HOST", "127.0.0.1")),
            port=int(pick_int(args.port, "IRI_MCP_PORT", 8000)),
            log_level=str(pick(args.log_level, "IRI_MCP_LOG_LEVEL", "INFO")),
            readonly_explicit=pick_bool(args.readonly, "IRI_MCP_READONLY", False),
            allow_submit=pick_bool(args.allow_submit, "IRI_MCP_ALLOW_SUBMIT", False),
            allow_fs_write=pick_bool(
                args.allow_fs_write, "IRI_MCP_ALLOW_FS_WRITE", False
            ),
            max_duration_sec=pick_int(
                args.max_duration_sec, "IRI_MCP_MAX_DURATION_SEC", 3600
            ),
            max_nodes=pick_int(args.max_nodes, "IRI_MCP_MAX_NODES", 8),
            max_processes_per_node=pick_int(
                args.max_processes_per_node, "IRI_MCP_MAX_PROCESSES_PER_NODE", 256
            ),
            max_read_bytes=int(
                pick_int(args.max_read_bytes, "IRI_MCP_MAX_READ_BYTES", 65536)
            ),
            max_lines=int(pick_int(args.max_lines, "IRI_MCP_MAX_LINES", 1000)),
            max_write_bytes=int(
                pick_int(args.max_write_bytes, "IRI_MCP_MAX_WRITE_BYTES", 1_048_576)
            ),
            allowed_queues=allowed_queues,
            audit_file=pick(args.audit_file, "IRI_MCP_AUDIT_FILE", None),
            compute_resource=str(
                pick(
                    args.compute_resource,
                    "IRI_MCP_COMPUTE_RESOURCE",
                    profile.compute_resource,
                )
            ),
            filesystem_resource=str(
                pick(
                    args.filesystem_resource,
                    "IRI_MCP_FILESYSTEM_RESOURCE",
                    profile.filesystem_resource,
                )
            ),
            wait_interval=float(
                pick(args.wait_interval, "IRI_MCP_WAIT_INTERVAL", 10.0)
            ),
        )


__all__ = ["Config", "DEFAULT_API_BASE_URL"]