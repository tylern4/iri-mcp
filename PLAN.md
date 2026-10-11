# PLAN — `iri-mcp`

An MCP server for the NERSC Integrated Research Infrastructure (IRI) API
(`https://api.iri.nersc.gov/api/v1`), exposing jobs, files, and facility status
as Model Context Protocol tools, prompts, and (stretch) resources. This is the
contract for the project and the substrate for a later phase-2 evaluation
harness that scores an agent's scientific workflow by driving the same code
paths through a thin `Runner` interface instead of an MCP transport.

This document is written before implementation (contract-first). Any deviation
from this contract must be recorded in §8 (Deviation log) and this section
updated to stay truthful.

---

## 1. Goals and non-goals

### Goals

- Expose the NERSC IRI API surface as MCP **tools** (observability, compute,
  filesystem), one **prompt**, and stretch **resources**, over `stdio` (default)
  and `streamable-http`.
- Be **agent-harness agnostic**: all copy (descriptions, prompt, docs) refers to
  the caller as "the assistant" / "the agent", never by a brand name.
- **Offline by default**: every test is hermetic (stubbed `AsyncClient` /
  canned HTTP). Live calls only when the operator sets `IRI_MCP_LIVE=1` and
  provides real credentials.
- **Safe by default**: read-only unless explicitly enabled; all caps enforced
  centrally in `safety.py`; an audit trail for every privileged call.
- Be the substrate for the phase-2 evaluation harness through a runner layer
  (`Runner`) with `submit / wait / read-file / checksum`.

### Non-goals (this phase)

- No new credential handling: the token is resolved lazily by the client from
  `access_token` arg → `IRI_API_TOKEN` → `~/.ssh/nersc-token`.
- No OAuth / token-minting / token refresh.
- No streaming of very large files; reads are size-capped by design.
- Not a general-purpose NERSC CLI; only the documented tool surface.
- Live (authenticated) testing is out of scope for CI and for this environment
  unless the user supplies a real account and sets `IRI_MCP_LIVE=1`.

---

## 2. Architecture

```
client = iri_client.AsyncClient        (token-free public endpoints OK)
   ▲
iri_mcp/config.py                     CLI flags + env (readonly default, caps, queues)
iri_mcp/safety.py                     Policy gate: mode + caps; audit log → stderr/file
iri_mcp/runner.py                     Runner (submit/wait/read-file/checksum) + IriRunner
iri_mcp/iritools/…                    tool handlers (observability / compute / filesystem)
   ▲
iri_mcp/server.py                     MCPServer("iri") wiring, transports, workflow prompt
```

Component responsibilities:

- `config.py` — `Config` model + `Config.load(argv, environ)` with precedence
  **CLI flags > env > defaults**. Command args: `--readonly` (default),
  `--allow-submit`, `--allow-fs-write`, `--max-duration-sec`, `--max-nodes`,
  `--max-processes-per-node`, `--max-read-bytes`, `--max-lines`,
  `--max-write-bytes`, `--allowed-queues`, `--audit-file`, `--transport`,
  `--host`, `--port`, `--api-base-url`, `--compute-resource`,
  `--filesystem-resource`, `--wait-interval`.
- `safety.py` — a single `Policy` object constructed from `Config`; every tool
  consults it through the runner. Raises `PolicyError` with actionable messages.
  Audit records are JSON lines to `--audit-file` or stderr (never stdout).
- `runner.py` — `Runner` abstract interface (`submit`, `wait`, `read_file`,
  `checksum`) that the phase-2 evaluator drives without MCP transport, plus
  `IriRunner`, the concrete implementation used by the tools. Tools are thin
  wrappers over the runner.
- `iritools/` — one module per surface (observability, compute, filesystem);
  coerces pydantic inputs → client calls → structured results; maps
  `IriError`/`AuthError`/`ResourceLookupError`/`TimeoutError` to friendly
  messages (see §3.5).
- `server.py` — builds `MCPServer(name="iri")`, registers tools/prompt/resources,
  and runs on `stdio` or `streamable-http` via `python -m iri_mcp`.

### Stdio discipline

In stdio mode nothing is ever written to stdout except JSON-RPC payloads written
by the SDK. All application logs go to stderr via `logging.getLogger(__name__)`.
No `print()`. Audit output defaults to stderr.

---

## 3. Security model

### 3.1 Modes and gates

| Privileged surface | Gate | Default | Enable |
|---|---|---|---|
| Job submit / cancel / run | `Policy.require_submit()` | **disabled** | `--allow-submit` (or `IRI_MCP_ALLOW_SUBMIT=1`) |
| Filesystem writes (mkdir/copy/move/remove/symlink/write_text) | `Policy.require_fs_write()` | **disabled** | `--allow-fs-write` (or `IRI_MCP_ALLOW_FS_WRITE=1`) |
| Everything else (observability, job listing/status/wait, fs reads) | none | enabled | — |

- The server is **read-only by default**: `readonly = explicit --readonly OR
  no allow-flag was provided`. Passing `--readonly` together with an allow flag
  is explicit and wins (the privileged ops stay disabled).
- `PolicyError` messages are actionable, e.g.:
  `submission disabled: server is in readonly mode; restart with --allow-submit`
  and `filesystem writes disabled: start with --allow-fs-write (or set
  IRI_MCP_ALLOW_FS_WRITE=1)`.

### 3.2 Caps (enforced centrally in `safety.py`)

| Cap | Flag / env | Default | Behavior |
|---|---|---|---|
| Job duration (seconds) | `--max-duration-sec` | 3600 | **reject** jobs requesting more |
| Node count | `--max-nodes` | 8 | **reject** jobs requesting more |
| Processes per node | `--max-processes-per-node` | 256 | **reject** jobs requesting more |
| Queue allowlist (comma list) | `--allowed-queues` | None (no restriction) | **reject** jobs on unlisted queues |
| Read size (bytes) | `--max-read-bytes` | 65536 (64 KiB) | **clamp** `fs_read` requests |
| Read line count | `--max-lines` | 1000 | **clamp** `fs_head`/`fs_tail` requests |
| File write size (bytes) | `--max-write-bytes` | 1 MiB | **reject** oversized `fs_write_text` |

Rationale: job-resource caps reject (irreversible, privileged); read caps clamp
(safe, avoids leaking large data); write caps reject (truncating a job script is
worse than an error). Rejections and clamps are surfaced in the tool result or
`is_error`.

### 3.3 Audit log

Every **privileged** call (submit, run, cancel, and all fs-write ops) and every
**policy denial** records a JSON line: `timestamp`, `tool`, `account`,
`caps_applied` (the caps that were checked/adjusted), plus operation-specific
fields (`job_id`, `path`, `reason`). Destination: `--audit-file PATH`, else
stderr. Never stdout. Audit writes are synchronous and best-effort (a failure
to write the audit file is logged, not fatal).

### 3.4 Credentials

No new secret handling. The client resolves a bearer token lazily:
`access_token` arg → `IRI_API_TOKEN` → `~/.ssh/nersc-token`. Token-free public
endpoints (facility, status, resource discovery) work with no token. Privileged
calls without a token surface `AuthError` as
`no credentials: set IRI_API_TOKEN or ~/.ssh/nersc-token`.

### 3.5 Error mapping

Tool handlers convert client exceptions to friendly `is_error` text (the MCP
client receives these in the tool result content):

| Client exception | Tool message |
|---|---|
| `SafetyPolicyError` (`PolicyError`) | the actionable policy message (see §3.1/§3.2) |
| `AuthError` | `no credentials: set IRI_API_TOKEN or ~/.ssh/nersc-token` |
| `ResourceLookupError` | `resource lookup failed: <message>` |
| `TimeoutError` | `<message>` (e.g. job did not reach a terminal state) |
| `IriError` | `IRI API error: <message>` |
| anything else | `unexpected error: <Type>: <message>` |

### 3.6 Residual risk (documented in README and PLAN)

MCP access grants whatever your credentials can do. Defense-in-depth, not a
guarantee: read-only default + central caps + client-side tool approval
(harness-level) + audit trail. An operator who enables `--allow-submit` and
`--allow-fs-write` and exposes the server to a network should treat it as a
privileged account. The `Runner` layer keeps the same gates in place if the
evaluation harness calls the runner directly.

---

## 4. Tool API contract (exact)

Input and output schemas are pydantic models; names listed here are the schema
names. All descriptions/copy are agent-harness agnostic ("the assistant").

### 4.0 Shared schema types

- `JobSpecInput` — mirrors the client `JobSpec` for the exposed subset:
  `name: str` (required), `executable: str` (required),
  `arguments: list[str] | None`, `directory: str | None`,
  `stdout_path: str | None`, `stderr_path: str | None`,
  `account: str` (required), `queue_name: str | None`,
  `duration: int | None` (seconds; capped), `node_count: int = 1` (capped),
  `processes_per_node: int = 1` (capped).
- `JobResult` — structured result for submit/get/wait/run tools:
  `job_id: str`, `state: str | None` (one of
  `new|queued|held|active|completed|failed|canceled`), `exit_code: int | None`,
  `message: str | None`, `submitted: bool`, `timed_out: bool`,
  `timeout_sec: float | None`, `stdout_tail: str | None`,
  `stderr_tail: str | None`, `tails_capped: bool`.
- `FS_*` read/write tools return plain strings, dicts, or lists of dicts
  (JSON-converted), as listed per tool.

### 4.1 Observability (all modes, token-free except `list_projects`)

1. `get_facility_info` — no args. Returns `client.facility.info()` (facility
   metadata dict).
2. `get_facility_sites` — no args. Returns `client.facility.sites()` (list of
   site dicts).
3. `get_resource_status` — no args. Returns
   `{"resources": client.status.resources(), "statuses": client.status.statuses()}`.
4. `get_incidents` — no args. Returns `client.status.incidents()` (list of
   incident dicts).
5. `list_projects` — no args. Returns `client.account.projects()` (list of
   project dicts). **Auth-gated by the client** (needs a token); no server-side
   gate beyond error mapping.

### 4.2 Compute (require `--allow-submit` for submit/run/cancel; list/get/wait need only a token)

6. `submit_job(spec: JobSpecInput)` → `JobResult`. Policy gate
   `require_submit`; caps checked on duration/node_count/processes_per_node/
   queue. Submits and returns the initial status with `submitted: true`.
7. `run_job(spec: JobSpecInput, timeout: float = 600)` → `JobResult`. Gate +
   caps as submit; submits, waits up to `timeout` seconds for a terminal state,
   then reads capped tails of `stdout_path`/`stderr_path` (when provided).
   `timed_out` indicates the wait exceeded `timeout` without reaching a
   terminal state.
8. `list_jobs(state: str | None, queue: str | None, limit: int | None = 50)` →
   `list[JobResult]` (no tails). `state` must be a valid `JobState` value
   (`new|queued|held|active|completed|failed|canceled`); the backend filter
   keys are `state` and `queue_name`.
9. `get_job(job_id: str)` → `JobResult` (single status fetch).
10. `wait_job(job_id: str, timeout: float = 600)` → `JobResult` (polls to
    terminal or timeout; capped tails included).
11. `cancel_job(job_id: str)` → confirmation string. Gate `require_submit`.

### 4.3 Filesystem read (all modes; token required by the client)

12. `fs_list(path: str, limit: int | None = 50)` → list of entry dicts
    (`name`, `type`, ...), truncated to `limit` after fetching.
13. `fs_head(path: str, lines: int = 10)` → string (first `lines` lines;
    clamped to `--max-lines`).
14. `fs_tail(path: str, lines: int = 10)` → string (last `lines` lines;
    clamped to `--max-lines`).
15. `fs_stat(path: str)` → stat dict.
16. `fs_checksum(path: str)` → SHA-256 hex string.
17. `fs_read(path: str, max_bytes: int | None = None)` → string. Reads the file
    as text via head-by-bytes; the request is clamped to `--max-read-bytes`
    (default cap when `max_bytes` omitted).

### 4.4 Filesystem write (require `--allow-fs-write`)

18. `fs_write_text(path: str, content: str)` → confirmation string. Size-checked
    against `--max-write-bytes` (reject). Intended for job scripts.
19. `fs_mkdir(path: str, parent: bool = True)` → confirmation string.
20. `fs_copy(path: str, target_path: str)` → confirmation string.
21. `fs_move(path: str, target_path: str)` → confirmation string.
22. `fs_remove(path: str)` → confirmation string.
23. `fs_symlink(path: str, link_path: str)` → confirmation string.

### 4.5 Prompt

`conduct-scientific-workflow` (registered as `@mcp.prompt(...)`), optional
`task: str | None` argument, returns instruction messages for the assistant:

- Start by checking `get_facility_info` and `get_resource_status`.
- Prefer `run_job` with short scripts for quick checks over interactive
  sessions (not available).
- Read failures with `fs_head`/`fs_tail` before retrying.
- Never invent an `account`, `queue_name`, or `duration` — confirm with the
  user. Stay within the server's documented caps.
- Verify outputs against expected values and `fs_checksum` where determinism is
  expected.
- Prefer unambiguous absolute paths on the shared filesystem.

### 4.6 Stretch resources (implemented after core, if time permits)

- `iri://jobs/{job_id}` — job status as JSON text.
- `iri://files/{path}` — file contents as text (path percent-encoded, e.g.
  `iri://files/%2Fpscratch%2Fsd%2Fe%2F...`); exempted from absolute-path
  security for remote paths. Slashes must be `%2F`-encoded.
- `streamable-http` transport via `mcp.streamable_http_app()` /
  `MCPServer.run(transport="streamable-http")`.

---

## 5. Runner interface (phase-2 substrate)

```python
class Runner(ABC):
    """Code paths the evaluation harness reuses without an MCP transport."""
    @abstractmethod
    async def submit(self, spec: JobSpecInput) -> JobResult: ...
    @abstractmethod
    async def wait(self, job_id: str, timeout: float | None) -> JobResult: ...
    @abstractmethod
    async def read_file(self, path: str, max_bytes: int | None = None) -> str: ...
    @abstractmethod
    async def checksum(self, path: str) -> str: ...
```

`IriRunner` implements these plus the remaining tool operations
(`get_job`, `list_jobs`, `cancel`, fs reads/writes) so every tool is a thin
wrapper over the runner and the evaluator exercises identical code paths,
including the `Policy` gates. Conversions:

- `submit` → `JobSpecInput` → client `JobSpec` (attributes/resources dicts).
- `wait` → poll job status every `--wait-interval` seconds until a terminal
  state or `timeout`; never raises on `failed`/`canceled`, returns the state.
- `read_file` → `fs.head(path, bytes_=clamped)`.
- `checksum` → `fs.checksum(path)`.

---

## 6. Configuration reference

Precedence: CLI flags > environment > defaults. Env names are `IRI_MCP_*`.

| Flag | Env | Default | Meaning |
|---|---|---|---|
| `--readonly` | `IRI_MCP_READONLY` | implicit | Force read-only (wins over allow flags) |
| `--allow-submit` | `IRI_MCP_ALLOW_SUBMIT` | off | Enable job submit/run/cancel |
| `--allow-fs-write` | `IRI_MCP_ALLOW_FS_WRITE` | off | Enable filesystem writes |
| `--max-duration-sec` | `IRI_MCP_MAX_DURATION_SEC` | 3600 | Job duration cap (reject) |
| `--max-nodes` | `IRI_MCP_MAX_NODES` | 8 | Node count cap (reject) |
| `--max-processes-per-node` | `IRI_MCP_MAX_PROCESSES_PER_NODE` | 256 | Processes/node cap (reject) |
| `--max-read-bytes` | `IRI_MCP_MAX_READ_BYTES` | 65536 | Read size cap (clamp) |
| `--max-lines` | `IRI_MCP_MAX_LINES` | 1000 | Read line cap (clamp) |
| `--max-write-bytes` | `IRI_MCP_MAX_WRITE_BYTES` | 1048576 | Write size cap (reject) |
| `--allowed-queues` | `IRI_MCP_ALLOWED_QUEUES` | — | Comma list; job queue must match |
| `--audit-file` | `IRI_MCP_AUDIT_FILE` | — | Audit JSONL path (else stderr) |
| `--transport` | `IRI_MCP_TRANSPORT` | stdio | `stdio` or `streamable-http` |
| `--host` / `--port` | `IRI_MCP_HOST` / `IRI_MCP_PORT` | 127.0.0.1 / 8000 | HTTP transport bind |
| `--api-base-url` | `IRI_MCP_API_BASE_URL` | `https://api.iri.nersc.gov/api/v1` | IRI API base (testing) |
| `--compute-resource` | `IRI_MCP_COMPUTE_RESOURCE` | `jobs` | Compute resource name/group |
| `--filesystem-resource` | `IRI_MCP_FILESYSTEM_RESOURCE` | `scratch` | Filesystem resource name/group |
| `--wait-interval` | `IRI_MCP_WAIT_INTERVAL` | 10 | Job/task poll interval (seconds) |
| `--log-level` | `IRI_MCP_LOG_LEVEL` | INFO | Server logging level |

---

## 7. Milestones / phases

- **M0 — Scaffold**: `uv init`, repo skeleton, `PLAN.md`, `AGENTS.md`,
  `pyproject.toml` (client from git `@main`; `mcp>=2.0`, `pydantic~=2.0`,
  `ruff`, `pytest`, `pytest-asyncio`). Commit.
  *Done when this contract is complete and schema types above are named.*
- **M1 — Core server**: `config.py`, `safety.py`, client factory, observability
  tools, stdio transport, `__main__`, hermetic tests.
  *Done when `uv run python -m iri_mcp` runs on stdio, `tools/list` exposes the
  observability tools, and offline tests pass.*
- **M2 — Compute layer**: `JobSpecInput`, gating, submit/list/status/wait/cancel/
  `run_job`, hermetic tests. Live smoke only if the user provides a real account
  (`IRI_MCP_LIVE=1`); otherwise skipped.
  *Done when offline tests pass.*
- **M3 — Filesystem + prompt + docs**: fs read + gated write tools, prompt,
  README, `docs/demo.md`, `scripts/smoke_mcp.sh`, GitHub Actions `pytest` CI.
  Stretch items if time permits.
  *Done when all Acceptance criteria below are verified.*
- **Phase 2 (out of scope here)**: evaluation harness driving `Runner` directly.

---

## 8. Deviation log

Recorded as encountered; nothing deviates from §4 as of M0. Because M0 is the
contract baseline, the first entry documents contract *additions* that are
explicitly permitted by the brief:

- **2026-10-11 (M0)** — Contract baseline. Additional (allowed) items beyond the
  brief's minimum: `--max-processes-per-node` and `--max-write-bytes` caps;
  `JobResult`/`JobSpecInput` structured schemas; `wait_job`/`run_job` return
  capped tails; `list_jobs` default `limit=50`; backend filter keys are
  `state`/`queue_name`. None of these change the required tool names or the
  gate/cap semantics.
- *(future entries appended here)*