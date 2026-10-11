# iri-mcp

A Model Context Protocol (MCP) server exposing the Integrated Research
Infrastructure (IRI) Facility API as MCP tools, a workflow prompt, and
read-only resources — so any agent harness can submit and monitor jobs, inspect
results, and manage files on HPC facility compute through standard MCP tool
calls.

The same IRI Facility API is implemented by several DOE facilities, and this
server speaks all of them — select one with `--facility` (see
[Facilities](#facilities)):

| `--facility` | Facility | API base URL |
| --- | --- | --- |
| `nersc` (default) | NERSC | `https://api.iri.nersc.gov/api/v1` |
| `alcf` | ALCF | `https://api.alcf.anl.gov/api/v1` |
| `esnet` | ESnet | `https://iri-dev.ppg.es.net/api/v1` |

> **Prototype status.** This is the first artifact of a larger plan: the same
> server becomes the substrate for an evaluation harness that scores whether an
> agent's scientific workflow is *correct*. The tool layer is therefore shaped
> as a thin `Runner` interface (`submit` / `wait` / `read-file` / `checksum`) so
> the evaluator can drive the exact same code paths without an MCP transport.

## Requirements

- Python ≥ 3.10
- `uv`
- IRI credentials only for privileged calls (see [Security](#security-model));
  observability tools are token-free.

## Install

```shell
uv sync --extra dev
```

## Quickstart (stdio)

```shell
uv run python -m iri_mcp                       # readonly, observability + fs reads
uv run python -m iri_mcp --allow-submit        # + job submit/run/cancel
uv run python -m iri_mcp --allow-submit --allow-fs-write   # + file writes
uv run python -m iri_mcp --facility alcf --allow-submit    # target ALCF instead
```

The server speaks MCP over stdio; register it in any client harness (opencode,
Claude Code, Claude Desktop, Cursor, or anything honoring the MCP spec — the
server name is `iri`). See [docs/](docs/) and the integration appendix in the
README.

## Facilities

All three facilities implement the same IRI Facility API, so the tool surface is
identical. A facility preset supplies the base URL, the resource names to bind,
how those resources are discovered, and where the bearer token comes from; any
of these can still be overridden with `--api-base-url`, `--compute-resource`,
`--filesystem-resource`, or `IRI_MCP_*` environment variables.

| Facility | Compute resource | Filesystem resource | Discovery | Token sources |
| --- | --- | --- | --- | --- |
| NERSC | `jobs` | `scratch` | `/compute/resources` | `IRI_API_TOKEN`, `~/.ssh/nersc-token` |
| ALCF | `Polaris` (also `Aurora`, `Crux`, …) | `Eagle` (also `Flare`, `Home`) | `/status/resources` | `ALCF_API_TOKEN`, `~/.ssh/alcf-token` |
| ESnet | `compute` (group) | `storage` (group) | `/compute/resources` | `ESNET_API_TOKEN`, `~/.ssh/esnet-token` |

Notes:

- **Discovery.** NERSC and ESnet implement the per-router discovery endpoints
  (`/compute/resources`, `/filesystem/resources`). ALCF returns HTTP 501 there,
  so it (and any deployment that stops implementing router discovery) is served
  from the public `/status/resources` list, filtered by `resource_type`.
- **Resource names.** `--compute-resource` / `--filesystem-resource` accept a
  resource id, name, or group; matching is case-insensitive. Use
  `get_resource_status` to list what a facility currently exposes.
- **Tokens.** Resolution order is `IRI_MCP_API_TOKEN`, the facility variable
  above, then the facility token file. If none is set the client falls back to
  `IRI_API_TOKEN` / `~/.ssh/nersc-token`. ALCF issues Globus-backed bearer
  tokens via `alcf-tokens` (see the [ALCF IRI API docs](https://docs.alcf.anl.gov/services/iri-api/)).
  Privileged calls only; public observability/read endpoints need no token.
- **ALCF caveat.** Resource ids at ALCF are UUIDs that can change; the `Polaris`
  / `Eagle` defaults are resolved by name through `/status/resources`, so they
  track the current deployment.

## Security model

- **Read-only by default.** Job submission/cancellation and filesystem writes
  are explicit opt-ins (`--allow-submit`, `--allow-fs-write`).
- **Caps enforced centrally** (duration, nodes, processes, queue allowlist,
  read size/lines, write size) — see `PLAN.md` §3.
- **Facility-aware token resolution, no new stores.** The token is resolved
  lazily from `IRI_MCP_API_TOKEN`, the selected facility's environment variable,
  or its token file (see [Facilities](#facilities)); nothing is cached or
  written.
- **Audit log** for every privileged call and policy denial (stderr or
  `--audit-file`).
- **Residual risk:** MCP access grants the harness whatever your credentials can
  do. The model here is defense-in-depth (read-only default + caps + client-side
  tool approval + audit), **not** a guarantee. Do not expose an enabled server
  to untrusted networks.

## Tool surface

Observability: `get_facility_info`, `get_facility_sites`, `get_resource_status`,
`get_incidents`, `list_projects`.

Compute (`--allow-submit`): `submit_job`, `run_job`, `list_jobs`, `get_job`,
`wait_job`, `cancel_job`.

Filesystem reads: `fs_list`, `fs_head`, `fs_tail`, `fs_stat`, `fs_checksum`,
`fs_read`.

Filesystem writes (`--allow-fs-write`): `fs_write_text`, `fs_mkdir`, `fs_copy`,
`fs_move`, `fs_remove`, `fs_symlink`.

Prompt: `conduct-scientific-workflow`.

Resources (read-only, always available): `iri://jobs/{job_id}` (job status as
JSON) and `iri://files{+path}` (capped text file contents; absolute remote paths
supported, traversal rejected).

Full contract and configuration reference: [`PLAN.md`](PLAN.md).

## Development

```shell
uv run ruff check .                  # lint
uv run pytest                        # hermetic offline tests
scripts/smoke_mcp.sh                 # stdio smoke: initialize → tools/list → one call
```

All tests are hermetic (canned HTTP / stubbed client). Live IRI calls require
`IRI_MCP_LIVE=1` and real credentials and are never run by CI.

## Layout

- `iri_mcp/config.py` — CLI flags + env, precedence CLI > env > defaults
- `iri_mcp/facilities.py` — NERSC/ALCF/ESnet presets (base URL, resources, tokens)
- `iri_mcp/safety.py` — `Policy` gate + caps + audit
- `iri_mcp/runner.py` — `Runner` interface + `IriRunner`
- `iri_mcp/iritools/` — tool handlers (observability / compute / filesystem)
- `iri_mcp/server.py` — `MCPServer("iri")` wiring and transports

See [`PLAN.md`](PLAN.md) for the architecture and API contract, and
[`AGENTS.md`](AGENTS.md) for the development checkpoints. An offline end-to-end
walkthrough (fake backend + real MCP client) is in [`docs/demo.md`](docs/demo.md).

## Integration appendix

The server speaks MCP over stdio; the server name is `iri`. In every harness
below the command is `uv run python -m iri_mcp` — replace `uv` with its
absolute path (`command -v uv`) in launchers that don't inherit your shell
environment, and add `--allow-submit` / `--allow-fs-write` to grant compute /
filesystem writes (see [Security model](#security-model)). Add
`--facility alcf` (or `esnet`) to target another facility.

The repo ships an [`opencode.json`](opencode.json) that wires the server up for
opencode out of the box.

### opencode

`opencode.json` at the repo root (already present):

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "servers": {
      "iri": {
        "type": "local",
        "command": ["uv", "run", "python", "-m", "iri_mcp"]
      }
    }
  }
}
```

Start opencode in the repo and the `iri_*` tools are available (readonly by
default). To use this config from any directory, replace `command` with an
absolute repo path: `["uv", "run", "--project", "/path/to/iri-mcp", "python",
"-m", "iri_mcp"]`, and add `"cwd": "/path/to/iri-mcp"`.

### Claude Desktop

Add to `claude_desktop_config.json` (Claude → Settings → Developer). Paths must
be absolute:

```json
{
  "mcpServers": {
    "iri": {
      "command": "/path/to/uv",
      "args": ["run", "--project", "/path/to/iri-mcp", "python", "-m", "iri_mcp"]
    }
  }
}
```

### Cursor

Place `.mcp.json` in the project root (Cursor runs the command from there):

```json
{
  "mcpServers": {
    "iri": {
      "command": "uv",
      "args": ["run", "python", "-m", "iri_mcp"]
    }
  }
}
```

### Any MCP client

Anything honoring the MCP spec can connect with the same shape: a stdio command
running `uv run python -m iri_mcp`, or a Streamable HTTP endpoint via
`python -m iri_mcp --transport streamable-http` (see `iri_mcp/server.py` for
the app factory and mount details).