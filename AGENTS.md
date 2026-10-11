# AGENTS — development log & checkpoints

Checkpoint log for `iri-mcp`. One entry per session/issue. Latest first.

## 2026-10-11 — Session 3 (dogfood): opencode config + unauthed verification

**What changed** — no repo source changes; harness integration verified end to end:

- Added the `iri` server to the **global** opencode config
  (`~/.config/opencode/opencode.json`) alongside the existing repo-scoped
  `./opencode.json`, so it resolves from any directory. Entry uses an absolute
  `--project` path: `uv run --project /home/ranger/github.com/iri-mcp python -m
  iri_mcp` (local, `type: local`), plus `$schema`. Repo working tree clean.
- `opencode mcp list` → `✓ iri connected` from both the repo (project config)
  and `/tmp/opencode` (global-only). A `opencode service restart` was needed for
  the running service to pick up the new global file (and to reload the server
  process onto post-M4 code — the previously-connected process predated the
  resource registration, so `resources/templates` were absent until the restart).

**Test evidence** — all four unauthenticated tools exercised through the live
opencode MCP connection (not in-process): `get_facility_info` (NERSC id/name/org/
`support_uri`/`site_uris`), `get_facility_sites` (LBNL site + `resource_uris`),
`get_resource_status` (37 resources, all `up`), `get_incidents` (~100 KB, planned/
unplanned). `list_mcp_resources` shows both templates registered:
`iri://files{+path}` (text/plain) and `iri://jobs/{job_id}` (application/json).
Auth gate confirmed friendly: `list_projects` and a `iri://jobs/{id}` resource
read with no token both return `no credentials: set IRI_API_TOKEN (or
ALCF_API_TOKEN / ESNET_API_TOKEN), or a token file such as ~/.ssh/nersc-token`
— no traceback. Repo `uv run pytest`/smoke unchanged (no code touched).

**Open issues** — dogfood covered the read-only surface only; privileged calls
(`--allow-submit` / `--allow-fs-write`) still not exercised under a harness (no
credentials here). Global config hardcodes the repo path — revisit if the repo
moves or is invoked via a wrapper.

## 2026-10-11 — Session 2 (M4): multi-facility (ALCF + ESnet)

**What changed** — the server now speaks every known IRI deployment, not just
NERSC; tool surface and §4 contract unchanged:

- `src/iri_mcp/facilities.py` (new) — `Facility` registry: `nersc` (default),
  `alcf`, `esnet`. Each preset carries base URL, compute/filesystem resource
  defaults, a discovery strategy (`router` vs `status`), token env vars, and a
  token file. Probed the live APIs first: ALCF `https://api.alcf.anl.gov/api/v1`
  (router discovery `/compute/resources` + `/filesystem/resources` return **501**;
  `/status/resources` is public and lists `Polaris`/`Aurora`/`Crux` compute and
  `Eagle`/`Flare`/`Home` storage); ESnet `https://iri-dev.ppg.es.net/api/v1`
  (compute group `compute`, storage group `storage`).
- `config.py` — `--facility` / `IRI_MCP_FACILITY` selector (+ validation);
  presets supply `--api-base-url` / `--compute-resource` / `--filesystem-resource`
  defaults, explicit flags still win; `Config.resolve_token()` + `.profile`
  / `.compute_discovery` / `.filesystem_discovery`.
- `runner.py` — `_compute` / `_filesystem` / `_resolve_resource` /
  `_discover_resources`; all 19 call sites now bind through them. `router`
  discovery, with a `status` strategy and a router→status fallback, using the
  client's `Resource` model + `ResourceType` filter; case-insensitive id/name/
  group matching with an "available: …" error. Direct construction of
  `AsyncCompute` / `AsyncFilesystem` from a resolved id (private client modules)
  avoids a second discovery round-trip per call.
- `errors.py` — `AUTH_HINT` names the facility token variables (keeps
  `IRI_API_TOKEN` for existing tests).
- `server.py` / `prompt.py` — server title/description/instructions and the
  workflow prompt render the selected facility's display name; server name stays
  `iri`.
- `tests/` — `test_facilities.py` (new: router vs status, 501 fallback,
  case-insensitive match, friendly unresolved-resource error); config tests for
  presets, override precedence, unknown facility, and token resolution;
  `test_server.py` identity/prompt facility-awareness; `fake_iri.py` gained
  `discovery_status` to simulate ALCF's 501.
- Docs: README (facilities table + section, security bullet, layout, appendix),
  PLAN §1/§2/§3.4/§3.5/§6 (facility presets) and §8 deviation entry,
  `docs/demo.md` note.

**Test evidence** — `uv run ruff check .` clean. `uv run pytest -q` →
**132 passed** (114 + 18). `scripts/smoke_mcp.sh` → **SMOKE PASS** (18 checks,
including the resource reads) against the NERSC fake.

**Open issues** — Live ALCF/ESnet calls not exercised (no accounts/tokens in
this environment; same `IRI_MCP_LIVE=1` restriction as NERSC). ESnet base URL is
the dev deployment (`iri-dev.ppg.es.net`) the user provided. ALCF `list_jobs`
filters use NERSC's `state`/`queue_name` keys, which ALCF's POST body may not
honor (listing itself works). `AsyncCompute`/`AsyncFilesystem` are imported from
private client modules — revisit if `nersc-iri-client` exports them. GitHub push
still deferred (no gh auth).

## 2026-10-11 — Session 1 (M3 stretch): resources + friendly 4xx

**What changed** — stretch resources implemented, plus a small error-mapping fix:

- `src/iri_mcp/iritools/resources.py` (new) — read-only resources registered in
  `build_server`:
  - `iri://jobs/{job_id}` → `get_job` serialized as JSON (`JobResult`).
  - `iri://files{+path}` → capped text file; `{+path}` reserved expansion keeps
    slashes literal so absolute paths work naturally
    (`iri://files/pscratch/sd/e/elvis/job.out`);
    `ResourceSecurity(reject_absolute_paths=False)` still rejects `..`/NUL.
  - `_friendly` wrapper (`functools.wraps` so the SDK can introspect template
    params) maps exceptions via `friendly_message` → `ResourceError`.
- `src/iri_mcp/errors.py` — `friendly_message` now maps `httpx.HTTPStatusError`
  → `IRI API error: HTTP <code> <reason> for <METHOD> <path>` (covers both tools
  and resources; previously a raw status dump).
- `tests/test_resources.py` (new, 8 tests) — template registration, job JSON,
  file read, credentials required, missing-job friendly error, traversal
  rejected, unknown URI.
- `scripts/smoke_client.py` — now also asserts `resources/templates` (both
  templates), a `jobs/{id}` JSON read, and a `files{+path}` read end to end.
- Docs/contract: README tool-surface + intro, `docs/demo.md`, PLAN §1/§2/§3.5/
  §4.6 and §8 deviation entry.

**Test evidence** — `uv run ruff check .` clean. `uv run pytest -q` →
**114 passed** (106 + 8 resources). `scripts/smoke_mcp.sh` → **SMOKE PASS** with
the three new resource checks.

**Open issues** — GitHub remote push still deferred (no gh auth). Live IRI
calls still blocked (no account/token; `IRI_MCP_LIVE=1` only). Client dep still
pinned to `@main` (pin to a tag before production); upstream `upload` fd leak
noted in PLAN §8. Privileged surface exercised under opencode only read-only.

## 2026-10-11 — Session 1 (M3): docs, CI, harness integration

**What changed** — M3 deliverables landed; smoke fixed and verified:

- `scripts/` (all three, committed): `fake_iri_http.py` (canned HTTP backend
  reusing `FakeIRI` via `httpx.Request` bridging; seeds hello.out/checksum),
  `smoke_client.py` (real MCP stdio client; fixed missing `import os` for the
  `env=dict(os.environ)` SDK allowlist workaround), `smoke_mcp.sh` (executable
  orchestrator, `set -euo pipefail`, trap kills backend, logs to
  `${TMPDIR}/iri-mcp-smoke`).
- `opencode.json` — V2 schema (`$schema` + `mcp.servers.iri`, `type: local`,
  readonly `uv run python -m iri_mcp`; `disabled` not `enabled` per V2 docs).
  Verified live: `opencode mcp list` → `✓ iri  connected`, and the `iri_*`
  tools appeared in the harness catalog.
- README: new "Integration appendix" (opencode / Claude Desktop absolute-path
  config / Cursor `.mcp.json` / generic stdio + streamable-http note) and a
  link to `docs/demo.md`.
- `docs/demo.md` — offline end-to-end walkthrough: what the smoke proves, exact
  output, anatomy of one `run_job` call, manual interactive demo, opencode
  note, live-mode caveat.
- `.github/workflows/ci.yml` — setup-uv + Python 3.10/3.11/3.12 matrix:
  `uv sync --extra dev`, `uv run ruff check .`, `uv run pytest -q`,
  `scripts/smoke_mcp.sh` (offline; no credentials needed).

**Test evidence** — `uv run ruff check .` clean. `uv run pytest -q` →
**106 passed** (~3.7s). `scripts/smoke_mcp.sh` → **SMOKE PASS** through
initialize / tools/list (23) / prompts/list / facility / resources / projects /
submit_job / run_job (tails) / wait_job / fs_head / fs_checksum over real
stdio+HTTP against the fake backend.

**Open issues** — GitHub remote push still deferred (no gh auth). Live IRI
calls still blocked (no account/token; `IRI_MCP_LIVE=1` only). Stretch
resources (`iri://jobs/{id}`, `iri://files/{path}`) and `ResourceSecurity`
not yet implemented; opencode read-only verified, privileged surface not
exercised under a harness.

## 2026-10-11 — Session 1 (cont.): implementation + hermetic tests

**What changed** — All M1/M2/M3 code landed and is covered by tests:

- `src/iri_mcp/`: `config.py`, `safety.py` (Policy gate + caps + AuditLog),
  `errors.py` (`iri_tool` → friendly `ToolError`), `client.py` (client_session
  factory), `runner.py` (`Runner` ABC + `IriRunner`: observability, compute,
  filesystem, tails, gated writes), `schemas.py` (`JobSpecInput`/`JobResult`),
  `prompt.py` (`conduct-scientific-workflow`), `server.py` (`build_server`,
  `main`), `__main__.py`, `iritools/{observability,compute,filesystem}.py`.
- `tests/`: `fake_iri.py` (stateful `httpx.MockTransport` fake), `helpers.py`,
  `conftest.py` (make_config/make_runner/make_server, quiet httpx logs), and
  `test_config/test_safety/test_observability/test_compute/test_filesystem/
  test_server/test_runner`.
- `pyproject.toml`: pytest `asyncio_mode=auto`; ruff isort
  `known-first-party = ["iri_mcp", "fake_iri", "helpers"]`.
- `PLAN.md` §8: SDK v2 behavior notes (see entry).

**Test evidence** — `uv run ruff check .` clean (E4/E7/E9/F/I/UP/B, all files
auto-fixed to PEP 585/604 + `collections.abc`). `uv run pytest` → **106 passed**
in ~4s, offline against the fake. Verified via `MCPServer.call_tool`:
23 tools + 1 prompt registered; protocol-level error conversion (ToolError
raises in-process, `is_error` on the wire); cap clamping observable in fake
query params; no-token runs yield the friendly credentials message.

**Open issues** — Live IRI calls still blocked (no account/token;
`IRI_MCP_LIVE=1` only). Upstream client `upload` leaks a multipart file object
per call (noted in PLAN §8). Remote push deferred (no gh auth).

## 2026-10-11 — Session 1 (M0: contract + scaffold)

**Context** — New project in `/home/ranger/github.com/iri-mcp` (empty dir).
`nersc-iri-client` cloned at `/home/ranger/github.com/nersc-iri-client` and read
as single source of truth for API surface. Verified MCP SDK v2 (`mcp 2.3.0`):
`MCPServer` replaces `FastMCP`; `@mcp.tool()`, `@mcp.prompt()`,
`@mcp.resource()`, `mcp.run(transport=...)`, `mcp.streamable_http_app()`;
`ToolError` carries friendly `is_error` text (from
`mcp.server.mcpserver.exceptions`).

**Decisions**

- Python ≥3.10, `uv`, package `src/` layout (`src/iri_mcp`), project name
  `iri-mcp`, version 0.1.0.
- Client dependency on the latest `main` of `tylern4/nersc-iri-client`
  (`git+https://...@main`) so CI works anywhere; a local clone exists for
  reading/iteration, not as a path dep in the committed pyproject.
- Git: branch `main`, remote `origin git@github.com:tylern4/iri-mcp.git`.
  **No GitHub token/gh auth in this environment** — user chose local commits;
  remote push deferred until the user creates the repo (or provides auth).
- Caps policy: job-resource caps **reject**, read caps **clamp**, write-size
  cap **reject** (recorded in PLAN §3.2/§8).
- `Runner` ABC (submit/wait/read-file/checksum) in `runner.py` is the phase-2
  substrate; `IriRunner` implements it plus all other tool ops.

**Contract** — `PLAN.md` written (numbered tool contract §4, security model §3,
schema types §4.0, Runner §5, config §6, milestones §7, deviations §8).
**AGENTS.md started (this file).**

**Status** — M0 in progress. Next: pin `pyproject.toml` deps, `.gitignore`,
LICENSE, first commit.

## Template for future entries

```
## YYYY-MM-DD — Session N (milestone)

**What changed** — bullet list of commits/files/behaviors.
**Test evidence** — `uv run pytest` counts; smoke script result; live runs.
**Open issues** — anything deferred, blocked, or needing user input.
```