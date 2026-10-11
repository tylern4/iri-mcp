# iri-mcp

A Model Context Protocol (MCP) server exposing the NERSC Integrated Research
Infrastructure (IRI) API ([`api.iri.nersc.gov`](https://api.iri.nersc.gov)) as
MCP tools, a workflow prompt, and (stretch) resources — so any agent harness
can submit and monitor jobs, inspect results, and manage files on NERSC compute
through standard MCP tool calls.

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
```

The server speaks MCP over stdio; register it in any client harness (opencode,
Claude Code, Claude Desktop, Cursor, or anything honoring the MCP spec — the
server name is `iri`). See [docs/](docs/) and the integration appendix in the
README.

## Security model

- **Read-only by default.** Job submission/cancellation and filesystem writes
  are explicit opt-ins (`--allow-submit`, `--allow-fs-write`).
- **Caps enforced centrally** (duration, nodes, processes, queue allowlist,
  read size/lines, write size) — see `PLAN.md` §3.
- **No new secret handling.** The IRI token is resolved lazily from
  `IRI_API_TOKEN` or `~/.ssh/nersc-token` by the client.
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
- `iri_mcp/safety.py` — `Policy` gate + caps + audit
- `iri_mcp/runner.py` — `Runner` interface + `IriRunner`
- `iri_mcp/iritools/` — tool handlers (observability / compute / filesystem)
- `iri_mcp/server.py` — `MCPServer("iri")` wiring and transports

See [`PLAN.md`](PLAN.md) for the architecture and API contract, and
[`AGENTS.md`](AGENTS.md) for the development checkpoints.