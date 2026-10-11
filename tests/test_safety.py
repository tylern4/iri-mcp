"""Policy gate: mode gates, job/read/write caps, and the audit log."""

from __future__ import annotations

import json
from typing import Any

import pytest

from iri_mcp.config import Config
from iri_mcp.safety import AuditLog, Policy, PolicyError
from iri_mcp.schemas import JobSpecInput


def make_policy(**overrides: Any) -> Policy:
    base: dict[str, Any] = dict(
        readonly=False,
        allow_submit=False,
        allow_fs_write=False,
        max_duration_sec=3600,
        max_nodes=8,
        max_processes_per_node=256,
        max_read_bytes=100,
        max_lines=10,
        max_write_bytes=100,
        allowed_queues=None,
        audit=AuditLog(),
    )
    base.update(overrides)
    return Policy(**base)


def spec(**over: Any) -> JobSpecInput:
    base: dict[str, Any] = dict(name="j", executable="/bin/echo", account="m0000")
    base.update(over)
    return JobSpecInput(**base)


class TestModeGates:
    def test_require_submit_denied_by_default(self):
        with pytest.raises(PolicyError, match="--allow-submit"):
            make_policy().require_submit(tool="submit_job")

    def test_require_submit_denied_when_readonly(self):
        with pytest.raises(PolicyError, match="readonly"):
            make_policy(readonly=True, allow_submit=True).require_submit(tool="submit_job")

    def test_require_submit_allowed(self):
        make_policy(allow_submit=True).require_submit(tool="submit_job")

    def test_require_fs_write_denied_by_default(self):
        with pytest.raises(PolicyError, match="--allow-fs-write"):
            make_policy().require_fs_write(tool="fs_write_text")

    def test_require_fs_write_denied_when_readonly(self):
        with pytest.raises(PolicyError, match="readonly"):
            make_policy(readonly=True, allow_fs_write=True).require_fs_write(
                tool="fs_write_text"
            )

    def test_require_fs_write_allowed(self):
        make_policy(allow_fs_write=True).require_fs_write(tool="fs_write_text")


class TestJobCaps:
    def test_duration_cap_rejected(self):
        with pytest.raises(PolicyError, match="duration"):
            make_policy(max_duration_sec=100).check_job(spec(duration=101))

    def test_node_cap_rejected(self):
        with pytest.raises(PolicyError, match="--max-nodes"):
            make_policy(max_nodes=2).check_job(spec(node_count=3))

    def test_processes_cap_rejected(self):
        with pytest.raises(PolicyError, match="--max-processes-per-node"):
            make_policy(max_processes_per_node=4).check_job(spec(processes_per_node=5))

    def test_queue_not_in_allowlist_rejected(self):
        with pytest.raises(PolicyError, match="queue 'regular'"):
            make_policy(allowed_queues=("debug",)).check_job(spec(queue_name="regular"))

    def test_within_caps_returns_applied_caps(self):
        policy = make_policy(allowed_queues=("debug", "regular"))
        caps = policy.check_job(
            spec(duration=60, node_count=1, processes_per_node=1, queue_name="debug")
        )
        assert caps == {
            "duration": 60,
            "node_count": 1,
            "processes_per_node": 1,
            "queue_name": "debug",
        }

    def test_none_fields_pass_through(self):
        caps = make_policy().check_job(
            spec(duration=None, node_count=1, processes_per_node=1, queue_name=None)
        )
        assert caps["duration"] is None
        assert caps["queue_name"] is None


class TestReadCapsClamp:
    def test_high_request_clamped(self):
        assert make_policy(max_read_bytes=100).cap_read_bytes(10_000) == 100

    def test_absent_request_uses_cap(self):
        assert make_policy(max_read_bytes=100).cap_read_bytes(None) == 100

    def test_small_request_kept(self):
        assert make_policy(max_read_bytes=100).cap_read_bytes(5) == 5

    def test_negative_request_floored(self):
        assert make_policy(max_read_bytes=100).cap_read_bytes(-5) == 0

    def test_lines_clamped_with_floor_of_one(self):
        policy = make_policy(max_lines=10)
        assert policy.cap_lines(100) == 10
        assert policy.cap_lines(None) == 10
        assert policy.cap_lines(3) == 3
        assert policy.cap_lines(0) == 1
        assert policy.cap_lines(-2) == 1


class TestWriteCapReject:
    def test_oversized_content_rejected(self):
        with pytest.raises(PolicyError, match="write cap"):
            make_policy(max_write_bytes=10).check_write_bytes(11)

    def test_at_cap_allowed(self):
        make_policy(max_write_bytes=10).check_write_bytes(10)


class TestAudit:
    def test_audit_log_writes_json_lines(self, tmp_path):
        path = tmp_path / "audit.jsonl"
        AuditLog(str(path)).record({"tool": "submit_job", "allowed": True, "account": "m0000"})
        event = json.loads(path.read_text().strip())
        assert event["tool"] == "submit_job"
        assert event["allowed"] is True
        assert event["account"] == "m0000"

    def test_denials_are_audited(self, tmp_path):
        path = tmp_path / "audit.jsonl"
        policy = make_policy(readonly=True, allow_submit=True, audit=AuditLog(str(path)))
        with pytest.raises(PolicyError):
            policy.require_submit(tool="submit_job")
        event = json.loads(path.read_text().strip())
        assert event["allowed"] is False
        assert event["tool"] == "submit_job"
        assert "readonly" in str(event["reason"])
        assert "ts" in event


class TestFromConfig:
    def test_policy_from_config_mirrors_config(self, tmp_path):
        cfg = Config.load(
            [
                "--allow-submit",
                "--max-nodes",
                "2",
                "--audit-file",
                str(tmp_path / "a.jsonl"),
            ],
            environ={},
        )
        policy = Policy.from_config(cfg)
        assert policy.allow_submit is True
        assert policy.readonly is False
        assert policy.max_nodes == 2
        assert policy.max_duration_sec == 3600
        with pytest.raises(PolicyError):
            policy.check_job(spec(node_count=3))


def test_deny_audit_records_tool_name(tmp_path):
    path = tmp_path / "audit.jsonl"
    policy = make_policy(readonly=True, allow_submit=True, audit=AuditLog(str(path)))
    with pytest.raises(PolicyError):
        policy.require_submit(tool="cancel_job")
    event = json.loads(path.read_text().strip())
    assert event["tool"] == "cancel_job"