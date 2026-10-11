"""Hermetic fake of the NERSC IRI API behind ``httpx.MockTransport``.

Stateful enough to exercise the client's job lifecycle (submit -> status ->
wait -> cancel), the async filesystem task queue, and the public endpoints
(facility/status). All requests (and their query params) are recorded for
assertions, e.g. verifying that the server clamped a read request to a cap.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import httpx


def _resource(
    resource_id: str,
    name: str,
    group: str,
    resource_type: str = "compute",
    status: str = "up",
) -> dict[str, Any]:
    return {
        "id": resource_id,
        "name": name,
        "group": group,
        "resource_type": resource_type,
        "current_status": status,
        "site_uri": "urn:site:perlmutter",
        "self_uri": resource_id,
        "capability_uris": [],
        "last_modified": "2026-01-01T00:00:00Z",
    }


def _facility() -> dict[str, Any]:
    return {
        "id": "urn:iri:facility:nersc",
        "name": "NERSC",
        "short_name": "NERSC",
        "organization_name": "Lawrence Berkeley National Laboratory",
        "self_uri": "urn:iri:facility:nersc",
        "site_uris": ["urn:site:perlmutter"],
        "last_modified": "2026-01-01T00:00:00Z",
    }


def _site() -> dict[str, Any]:
    return {
        "id": "urn:site:perlmutter",
        "name": "Perlmutter",
        "operating_organization": "Lawrence Berkeley National Laboratory",
        "self_uri": "urn:site:perlmutter",
        "resource_uris": [],
        "last_modified": "2026-01-01T00:00:00Z",
    }


def _incident() -> dict[str, Any]:
    return {
        "id": "urn:iri:incident:1",
        "name": "Planned maintenance",
        "status": "up",
        "type": "planned",
        "resolution": "completed",
        "start": "2026-01-01T00:00:00Z",
        "self_uri": "urn:iri:incident:1",
        "event_uris": [],
        "resource_uris": [],
        "last_modified": "2026-01-01T00:00:00Z",
    }


def _project() -> dict[str, Any]:
    return {
        "id": "proj-abc123",
        "name": "Climate Simulation",
        "description": "Research project studying atmospheric dynamics.",
        "user_ids": ["user-123"],
        "last_modified": "2026-01-01T00:00:00Z",
        "self_uri": "urn:iri:project:abc123",
    }


COMPUTE_RESOURCES = [
    _resource("urn:iri:resource:jobs", "Perlmutter", "jobs"),
    _resource("urn:iri:resource:compute", "Perlmutter GPU", "compute"),
]
FILESYSTEM_RESOURCES = [
    _resource("urn:iri:resource:scratch", "Perlmutter Scratch", "scratch", "storage"),
    _resource("urn:iri:resource:homes", "Storage Homes", "homes", "storage"),
    _resource("urn:iri:resource:jobs", "Perlmutter", "jobs"),
]
STATUS_RESOURCES = [
    _resource("urn:iri:resource:jobs", "Perlmutter", "jobs"),
    _resource("urn:iri:resource:scratch", "Perlmutter Scratch", "scratch", "storage", "unknown"),
]


@dataclass
class FakeIRI:
    """Stateful fake IRI API served through ``httpx.MockTransport``."""

    files: dict[str, str] = field(default_factory=dict)
    """path -> text content served by head/tail/view/download."""

    checksums: dict[str, str] = field(default_factory=dict)
    """path -> hex checksum served by checksum."""

    errors: set = field(default_factory=set)
    """paths whose filesystem operations fail with an 'error' task result."""

    projects: list[dict[str, Any]] = field(default_factory=lambda: [_project()])

    auto_complete: bool = True
    """When True, freshly submitted jobs immediately reach 'completed' (exit 0)."""

    discovery_status: int | None = None
    """When set, ``compute/resources`` and ``filesystem/resources`` fail with
    this HTTP status (e.g. 501, as ALCF does); status-based discovery is used."""

    calls: list[tuple[str, str]] = field(default_factory=list)
    """(method, api-key) for every request."""

    param_calls: list[tuple[str, str, dict[str, str]]] = field(default_factory=list)
    """(method, api-key, query-params) for every request."""

    bodies: list[dict[str, Any]] = field(default_factory=list)
    """JSON bodies of POST/PUT requests."""

    jobs: dict[str, dict[str, Any]] = field(default_factory=dict)
    """job_id -> job document {"id", "status", "job_spec"}."""

    _job_counter: int = 0
    _task_counter: int = 0
    _tasks: dict[str, dict[str, Any]] = field(default_factory=dict)
    _dirs: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    # -- seeding ---------------------------------------------------------

    def seed_job(
        self,
        job_id: str,
        state: str = "queued",
        exit_code: int | None = None,
        message: str | None = None,
        job_spec: dict[str, Any] | None = None,
    ) -> None:
        self.jobs[job_id] = {
            "id": job_id,
            "status": {
                "state": state,
                "time": 1700000000.0,
                "message": message,
                "exit_code": exit_code,
            },
            "job_spec": job_spec or {},
        }

    def seed_dir(self, path: str, entries: list[dict[str, Any]]) -> None:
        self._dirs[path] = entries

    def new_task_id(self) -> str:
        self._task_counter += 1
        return f"task-{self._task_counter}"

    # -- handlers --------------------------------------------------------

    def _respond(self, payload: Any, status: int = 200) -> httpx.Response:
        return httpx.Response(status, json=payload)

    def handler(self, request: httpx.Request) -> httpx.Response:
        key = request.url.path.split("/api/v1/", 1)[-1]
        params = dict(request.url.params)
        self.calls.append((request.method, key))
        self.param_calls.append((request.method, key, params))

        if request.content:
            content_type = request.headers.get("content-type", "")
            if "application/json" in content_type or content_type == "":
                try:
                    self.bodies.append(json.loads(request.content))
                except ValueError:
                    pass

        if key == "facility":
            return self._respond(_facility())
        if key == "facility/sites":
            return self._respond([_site()])
        if key == "status/resources":
            return self._respond(STATUS_RESOURCES)
        if key == "status/incidents":
            return self._respond([_incident()])
        if key == "account/projects":
            return self._respond(self.projects)
        if key == "compute/resources":
            if self.discovery_status is not None:
                return self._respond({"detail": "Not implemented yet."}, self.discovery_status)
            return self._respond(COMPUTE_RESOURCES)
        if key == "filesystem/resources":
            if self.discovery_status is not None:
                return self._respond({"detail": "Not implemented yet."}, self.discovery_status)
            return self._respond(FILESYSTEM_RESOURCES)

        if key.startswith("compute/job/"):
            body = self.bodies[-1] if self.bodies else {}
            return self._submit_job(body)
        if key.startswith("compute/cancel/"):
            job_id = key.rsplit("/", 1)[-1]
            return self._cancel_job(job_id)
        if key == "compute/status" or key.startswith("compute/status/"):
            return self._compute_status(request.method, key, params)
        if key.startswith("task/"):
            return self._task_result(key.rsplit("/", 1)[-1])
        if key.startswith("filesystem/"):
            parts = key.split("/")
            if len(parts) < 3:
                return self._respond({"error": f"no fake for {key}"}, 404)
            return self._fs_submit(parts[1], request.method, params)

        return self._respond({"error": f"no fake for {key}"}, 404)

    # -- compute ---------------------------------------------------------

    def _submit_job(self, body: dict[str, Any]) -> httpx.Response:
        self._job_counter += 1
        job_id = f"job-{self._job_counter}"
        if self.auto_complete:
            state, exit_code = "completed", 0
        else:
            state, exit_code = "queued", None
        self.jobs[job_id] = {
            "id": job_id,
            "status": {"state": state, "time": 1700000000.0, "message": None, "exit_code": exit_code},
            "job_spec": body,
        }
        return self._respond({"id": job_id})

    def _cancel_job(self, job_id: str) -> httpx.Response:
        if job_id in self.jobs:
            self.jobs[job_id]["status"]["state"] = "canceled"
        return self._respond({"ok": True})

    def _compute_status(
        self, method: str, key: str, params: dict[str, str]
    ) -> httpx.Response:
        parts = key.split("/")
        # POST compute/status/{compute-id} -> list jobs
        if method == "POST":
            body = self.bodies[-1] if self.bodies else {}
            filters = body.get("filters", body) if isinstance(body, dict) else body
            state = filters.get("state")
            queue = filters.get("queue_name")
            limit = int(params.get("limit", 0)) or None
            matches = []
            for job_id, doc in sorted(self.jobs.items()):
                status = doc.get("status", {})
                if state is not None and status.get("state") != state:
                    continue
                if queue is not None:
                    spec = doc.get("job_spec", {})
                    attrs = spec.get("attributes", {}) or {}
                    if attrs.get("queue_name") != queue:
                        continue
                matches.append({"id": job_id})
            if limit is not None:
                matches = matches[:limit]
            return self._respond(matches)
        # GET compute/status/{compute-id}/{job-id}
        job_id = parts[-1]
        doc = self.jobs.get(job_id)
        if doc is None:
            return self._respond({"error": f"no job {job_id}"}, 404)
        return self._respond(doc)

    # -- filesystem ------------------------------------------------------

    def _fs_submit(self, command: str, method: str, params: dict[str, str]) -> httpx.Response:
        task_id = self.new_task_id()
        self._tasks[task_id] = {"command": command, "params": params}
        return self._respond(
            {"task_id": task_id, "task_uri": f"/api/v1/task/{task_id}"}
        )

    def _task_result(self, task_id: str) -> httpx.Response:
        task = self._tasks.get(task_id)
        if task is None:
            return self._respond({"error": f"no task {task_id}"}, 404)
        command = task["command"]
        params = task["params"]
        path = params.get("path")
        if path in self.errors:
            # The real backend reports failures as a *completed* task whose
            # result carries an "error" member (see iri_client tasks.py).
            return self._respond(
                {
                    "id": task_id,
                    "status": "completed",
                    "result": {"error": f"no such file or directory: {path}"},
                }
            )
        if command == "ls":
            return self._respond(
                {
                    "id": task_id,
                    "status": "completed",
                    "result": {"output": self._dirs.get(path, [])},
                }
            )
        if command == "stat":
            return self._respond(
                {
                    "id": task_id,
                    "status": "completed",
                    "result": {
                        "output": {
                            "path": path,
                            "mode": 33188,
                            "ino": 42,
                            "size": len(self.files.get(path, "")),
                        }
                    },
                }
            )
        if command in ("head", "tail", "view", "download"):
            return self._respond(
                {
                    "id": task_id,
                    "status": "completed",
                    "result": {"output": {"content": self.files.get(path, "")}},
                }
            )
        if command == "checksum":
            return self._respond(
                {
                    "id": task_id,
                    "status": "completed",
                    "result": {
                        "output": {
                            "checksum": self.checksums.get(
                                path, "0" * 64
                            )
                        }
                    },
                }
            )
        # mutating commands: confirmation with no payload
        return self._respond(
            {"id": task_id, "status": "completed", "result": {"output": None}}
        )


__all__ = ["FakeIRI"]