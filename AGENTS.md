# AGENTS — development log & checkpoints

Checkpoint log for `iri-mcp`. One entry per session/issue. Latest first.

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