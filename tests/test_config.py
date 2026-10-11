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


# ---------------------------------------------------------------------------
# Facility selection
# ---------------------------------------------------------------------------


def test_facility_default_is_nersc():
    cfg = Config.load([], environ={})
    assert cfg.facility == "nersc"
    assert cfg.profile.display_name == "NERSC"
    assert cfg.api_base_url == "https://api.iri.nersc.gov/api/v1"
    assert cfg.compute_resource == "jobs"
    assert cfg.filesystem_resource == "scratch"
    assert cfg.compute_discovery == "router"
    assert cfg.filesystem_discovery == "router"


def test_facility_alcf_defaults():
    cfg = Config.load(["--facility", "alcf"], environ={})
    assert cfg.facility == "alcf"
    assert cfg.profile.display_name == "ALCF"
    assert cfg.api_base_url == "https://api.alcf.anl.gov/api/v1"
    assert cfg.compute_resource == "Polaris"
    assert cfg.filesystem_resource == "Eagle"
    # ALCF returns 501 on router discovery, so it resolves via /status/resources.
    assert cfg.compute_discovery == "status"
    assert cfg.filesystem_discovery == "status"


def test_facility_esnet_defaults():
    cfg = Config.load(["--facility", "esnet"], environ={})
    assert cfg.facility == "esnet"
    assert cfg.api_base_url == "https://iri-dev.ppg.es.net/api/v1"
    assert cfg.compute_resource == "compute"
    assert cfg.filesystem_resource == "storage"
    assert cfg.compute_discovery == "router"


def test_facility_from_env_and_cli_precedence():
    assert Config.load([], environ={"IRI_MCP_FACILITY": "alcf"}).facility == "alcf"
    cfg = Config.load(["--facility", "esnet"], environ={"IRI_MCP_FACILITY": "alcf"})
    assert cfg.facility == "esnet"


def test_explicit_resources_override_facility_defaults():
    cfg = Config.load(
        [
            "--facility",
            "alcf",
            "--compute-resource",
            "Aurora",
            "--filesystem-resource",
            "Flare",
        ],
        environ={},
    )
    assert cfg.compute_resource == "Aurora"
    assert cfg.filesystem_resource == "Flare"


def test_unknown_facility_rejected():
    with pytest.raises(ValueError):
        Config.load([], environ={"IRI_MCP_FACILITY": "nope"})
    with pytest.raises(ValueError):
        Config(facility="nope")


# ---------------------------------------------------------------------------
# Token resolution
# ---------------------------------------------------------------------------


def test_resolve_token_generic_override_wins():
    cfg = Config.load(["--facility", "alcf"], environ={})
    token = cfg.resolve_token(
        environ={"IRI_MCP_API_TOKEN": "generic", "ALCF_API_TOKEN": "facility"}
    )
    assert token == "generic"


def test_resolve_token_facility_env():
    cfg = Config.load(["--facility", "alcf"], environ={})
    assert cfg.resolve_token(environ={"ALCF_API_TOKEN": "alcf-tok"}) == "alcf-tok"


def test_resolve_token_from_facility_file(tmp_path, monkeypatch):
    from iri_mcp import facilities as facilities_mod

    token_file = tmp_path / "alcf-token"
    token_file.write_text("file-token\n")
    monkeypatch.setitem(
        facilities_mod.FACILITIES,
        "alcf",
        facilities_mod.FACILITIES["alcf"].model_copy(
            update={"token_file": str(token_file)}
        ),
    )
    cfg = Config.load(["--facility", "alcf"], environ={})
    assert cfg.resolve_token(environ={}) == "file-token"


def test_resolve_token_none_when_absent(monkeypatch):
    from iri_mcp import facilities as facilities_mod

    monkeypatch.setitem(
        facilities_mod.FACILITIES,
        "esnet",
        facilities_mod.FACILITIES["esnet"].model_copy(update={"token_file": None}),
    )
    cfg = Config.load(["--facility", "esnet"], environ={})
    assert cfg.resolve_token(environ={}) is None