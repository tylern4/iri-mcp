"""Config parsing: defaults, CLI > env > defaults precedence, and mode gates."""

from __future__ import annotations

import pytest

from iri_mcp.config import DEFAULT_API_BASE_URL, Config


def test_defaults_are_readonly_with_caps():
    cfg = Config.load([], environ={})
    assert cfg.readonly is True
    assert cfg.allow_submit is False
    assert cfg.allow_fs_write is False
    assert cfg.transport == "stdio"
    assert cfg.api_base_url == DEFAULT_API_BASE_URL
    assert cfg.max_duration_sec == 3600
    assert cfg.max_nodes == 8
    assert cfg.max_processes_per_node == 256
    assert cfg.max_read_bytes == 65536
    assert cfg.max_lines == 1000
    assert cfg.max_write_bytes == 1_048_576
    assert cfg.allowed_queues is None
    assert cfg.compute_resource == "jobs"
    assert cfg.filesystem_resource == "scratch"
    assert cfg.wait_interval == 10.0
    assert cfg.audit_file is None


def test_cli_flags_override_defaults():
    cfg = Config.load(
        [
            "--allow-submit",
            "--allow-fs-write",
            "--max-nodes",
            "2",
            "--max-lines",
            "25",
            "--max-duration-sec",
            "120",
            "--allowed-queues",
            "debug",
            "--allowed-queues",
            "regular",
        ],
        environ={},
    )
    assert cfg.allow_submit is True
    assert cfg.allow_fs_write is True
    assert cfg.readonly is False
    assert cfg.max_nodes == 2
    assert cfg.max_lines == 25
    assert cfg.max_duration_sec == 120
    assert cfg.allowed_queues == ("debug", "regular")


def test_env_fallbacks():
    cfg = Config.load(
        [],
        environ={
            "IRI_MCP_ALLOW_SUBMIT": "1",
            "IRI_MCP_MAX_READ_BYTES": "1024",
            "IRI_MCP_TRANSPORT": "streamable-http",
            "IRI_MCP_PORT": "9000",
            "IRI_MCP_ALLOWED_QUEUES": "debug, regular",
        },
    )
    assert cfg.allow_submit is True
    assert cfg.max_read_bytes == 1024
    assert cfg.transport == "streamable-http"
    assert cfg.port == 9000
    assert cfg.allowed_queues == ("debug", "regular")


def test_cli_beats_env():
    cfg = Config.load(["--max-nodes", "2"], environ={"IRI_MCP_MAX_NODES": "9"})
    assert cfg.max_nodes == 2


def test_empty_env_value_ignored():
    cfg = Config.load([], environ={"IRI_MCP_ALLOW_SUBMIT": ""})
    assert cfg.allow_submit is False


def test_mode_gate_properties():
    plain = Config.load([], environ={})
    assert plain.readonly is True
    assert plain.submit_enabled is False
    assert plain.fs_write_enabled is False

    submit = Config.load(["--allow-submit"], environ={})
    assert submit.readonly is False
    assert submit.submit_enabled is True
    assert submit.fs_write_enabled is False

    fs = Config.load(["--allow-fs-write"], environ={})
    assert fs.readonly is False
    assert fs.submit_enabled is False
    assert fs.fs_write_enabled is True


def test_explicit_readonly_overrides_privilege_flags():
    cfg = Config.load(["--readonly", "--allow-submit", "--allow-fs-write"], environ={})
    assert cfg.readonly is True
    assert cfg.submit_enabled is False
    assert cfg.fs_write_enabled is False


def test_invalid_transport_rejected():
    with pytest.raises(ValueError):
        Config(transport="bogus")