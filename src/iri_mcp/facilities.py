"""Known IRI facilities and their per-deployment defaults.

NERSC, ALCF, and ESnet all implement the same IRI Facility API (``/api/v1``),
so the MCP surface is identical; what differs is the base URL, the names/ids of
the compute and filesystem resources, how those resources are discovered, and
where the bearer token comes from. A :class:`Facility` captures those
differences so the rest of the server stays facility-agnostic.

Discovery strategies:

- ``"router"`` — the deployment implements the per-router discovery endpoints
  ``GET /compute/resources`` and ``GET /filesystem/resources`` (NERSC, ESnet).
- ``"status"`` — use the public ``GET /status/resources`` list and filter by
  ``resource_type`` (ALCF; its router discovery endpoints return HTTP 501).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from pydantic import BaseModel, ConfigDict

DEFAULT_FACILITY = "nersc"


class Facility(BaseModel):
    """Per-deployment IRI bindings and defaults."""

    model_config = ConfigDict(frozen=True)

    key: str
    display_name: str
    base_url: str
    compute_resource: str
    filesystem_resource: str
    compute_discovery: str = "router"
    filesystem_discovery: str = "router"
    token_env: tuple[str, ...] = ()
    token_file: str | None = None
    notes: str = ""


FACILITIES: dict[str, Facility] = {
    "nersc": Facility(
        key="nersc",
        display_name="NERSC",
        base_url="https://api.iri.nersc.gov/api/v1",
        compute_resource="jobs",
        filesystem_resource="scratch",
        compute_discovery="router",
        filesystem_discovery="router",
        token_env=("IRI_API_TOKEN",),
        token_file="~/.ssh/nersc-token",
        notes="Perlmutter. Router discovery and the default resource names.",
    ),
    "alcf": Facility(
        key="alcf",
        display_name="ALCF",
        base_url="https://api.alcf.anl.gov/api/v1",
        # Compute/FS are addressed by name here; ALCF resolves them to the
        # current resource UUIDs behind the scenes.
        compute_resource="Polaris",
        filesystem_resource="Eagle",
        # ALCF returns 501 on /compute/resources and /filesystem/resources, so
        # resources are resolved from the public /status/resources list instead.
        compute_discovery="status",
        filesystem_discovery="status",
        token_env=("ALCF_API_TOKEN",),
        token_file="~/.ssh/alcf-token",
        notes=(
            "Compute: Aurora, Polaris, Crux (also Sirius, Edith). "
            "Filesystems: Home, Flare, Eagle. Tokens are Globus-issued "
            "(`alcf-tokens login iri`); resource discovery uses /status/resources."
        ),
    ),
    "esnet": Facility(
        key="esnet",
        display_name="ESnet",
        base_url="https://iri-dev.ppg.es.net/api/v1",
        # ESnet names its compute resource "Low Priority compute" in group
        # "compute"; storages ("Storage", "Home Filesystem", ...) are in group
        # "storage", so the group is the stable selector.
        compute_resource="compute",
        filesystem_resource="storage",
        compute_discovery="router",
        filesystem_discovery="router",
        token_env=("ESNET_API_TOKEN",),
        token_file="~/.ssh/esnet-token",
        notes="Development IRI deployment at iri-dev.ppg.es.net.",
    ),
}


def facility_for(key: str) -> Facility:
    """Return the :class:`Facility` for ``key`` (case-insensitive)."""
    try:
        return FACILITIES[key.strip().lower()]
    except KeyError:
        known = ", ".join(sorted(FACILITIES))
        raise ValueError(f"unknown facility {key!r}; known facilities: {known}") from None


def resolve_token(
    facility: Facility,
    environ: Mapping[str, str] | None = None,
) -> str | None:
    """Resolve a bearer token for ``facility`` from the environment or token file.

    Order: the generic ``IRI_MCP_API_TOKEN`` override, then the facility's
    ``token_env`` variables, then its ``token_file``. Returns ``None`` when no
    source has a token (the client then falls back to ``IRI_API_TOKEN`` /
    ``~/.ssh/nersc-token``).
    """
    env = os.environ if environ is None else environ
    for name in ("IRI_MCP_API_TOKEN", *facility.token_env):
        value = env.get(name)
        if value:
            return value
    if facility.token_file:
        path = Path(facility.token_file).expanduser()
        try:
            if path.is_file():
                token = path.read_text().strip()
                if token:
                    return token
        except OSError:
            pass
    return None


__all__ = [
    "DEFAULT_FACILITY",
    "FACILITIES",
    "Facility",
    "facility_for",
    "resolve_token",
]
