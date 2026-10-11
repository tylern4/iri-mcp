# Demo: iri-mcp end to end (offline)

This walkthrough shows the whole system working without touching a live facility
API: a canned fake backend, a real `iri-mcp` server over MCP stdio, and a real
MCP client driving it like an agent harness would.

The fake implements the same IRI Facility API contract as NERSC, ALCF, and
ESnet, so the same smoke exercises any `--facility` preset; the script runs with
the default (`nersc`) and its fake reports itself as NERSC. To point a real
server at another facility, add `--facility alcf` (or `esnet`) — see the README
[Facilities](../README.md#facilities) section.

## What it proves

- `initialize` handshake and `tools/list` (23 tools) / `prompts/list` (1 prompt)
- Observability: `get_facility_info`, `get_resource_status`, `list_projects`
- Compute (`--allow-submit`): `submit_job`, `run_job` (submit → poll → tails),
  `wait_job`
- Filesystem: `fs_head`, `fs_checksum` (plus `submit_job` ran with
  `--allow-fs-write` so `stdout_path` targeting works for tail recovery)
- Resources (`resources/templates` + `resources/read`): `iri://jobs/{job_id}`
  and `iri://files{+path}`
- A real `uv run python -m iri_mcp` subprocess speaking protocol on stdio

## Run it

```shell
uv sync --extra dev
scripts/smoke_mcp.sh
```

Expected tail of the output:

```text
ok   tools/list exposes 23 tools
ok   tools/list names match contract
ok   prompts/list has conduct-scientific-workflow
ok   get_facility_info returns NERSC
ok   get_resource_status lists resources
ok   list_projects returns a project
ok   submit_job returns job_id
ok   run_job reaches completed
ok   run_job exit code 0
ok   run_job returns stdout tail
ok   wait_job completes submitted job
ok   fs_head reads the output file
ok   fs_checksum returns hex checksum
ok   resources/templates exposes job + file templates
ok   job resource returns completed JSON
ok   file resource reads the output file
SMOKE PASS
```

Logs land in `${TMPDIR:-/tmp}/iri-mcp-smoke/` (`fake.log`, server stderr with
audit lines, etc.). The smoke script is what CI runs
([`.github/workflows/ci.yml`](../.github/workflows/ci.yml)).

## What the client is doing

`scripts/smoke_client.py` is a hand-written MCP stdio client using the official
`mcp` SDK. The interesting pieces:

- `StdioServerParameters(env=dict(os.environ))` — the SDK only inherits an env
  allowlist, so the server needs the caller's full environment (here just the
  placeholder `IRI_API_TOKEN`).
- `ClientSession.call_tool` drives the same wire protocol a harness uses; a
  failed call arrives with `is_error=True`, never an exception.

## Anatomy of one agent-style call

A harness asks the model to run a job; the model calls:

```json
{
  "name": "run_job",
  "arguments": {
    "spec": {
      "name": "hello",
      "executable": "/bin/echo",
      "arguments": ["hello iri"],
      "directory": "/pscratch/sd/e/elvis/tmp",
      "stdout_path": "/pscratch/sd/e/elvis/tmp/hello.out",
      "stderr_path": "/pscratch/sd/e/elvis/tmp/hello.err",
      "account": "m0000",
      "queue_name": "debug",
      "duration": 60,
      "node_count": 1,
      "processes_per_node": 1
    },
    "timeout": 5.0
  }
}
```

The server submits, polls (`--wait-interval`), and returns a single
`JobResult` with `state: "completed"`, `exit_code: 0`, and a 50-line capped
stdout tail — everything an agent needs to decide what happened without a
second round trip.

## Manual interactive demo

To poke at individual tools (same shape as a harness): start the fake backend
in one terminal, then a server pointed at it in another:

```shell
uv run python scripts/fake_iri_http.py --port 8971
IRI_API_TOKEN=smoke-token uv run python -m iri_mcp \
  --api-base-url http://127.0.0.1:8971/api/v1 \
  --allow-submit --allow-fs-write --log-level WARNING
```

Then connect any MCP client to that server. `scripts/smoke_client.py` is the
reference client and accepts the same flags:

```shell
IRI_API_TOKEN=smoke-token uv run python scripts/smoke_client.py \
  --base-url http://127.0.0.1:8971/api/v1 --allow-submit --allow-fs-write
```

## In opencode

The repo ships an [`opencode.json`](../opencode.json) that registers the server
as `iri`. Open a session in this repo and the `iri_*` tools are available
(readonly by default — see the [integration appendix](../README.md#integration-appendix)
for enabling compute/filesystem writes). To exercise the full privileged
surface under a harness locally, point the server at the fake backend by
editing the command in `opencode.json` to add `--api-base-url
http://127.0.0.1:8971/api/v1 --allow-submit --allow-fs-write` and run
`scripts/fake_iri_http.py` first.

## Live mode

The same server works against the real API — no code changes, just credentials:

```shell
# with a real IRI account:
uv run python -m iri_mcp --allow-submit --allow-fs-write
```

Live runs are never part of CI. Tests and the smoke stay hermetic.