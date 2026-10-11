#!/usr/bin/env bash
# Offline end-to-end smoke for iri-mcp.
#
# Starts the canned fake IRI backend (scripts/fake_iri_http.py), spawns a real
# iri-mcp server on stdio pointed at it, and drives it with a real MCP client
# (scripts/smoke_client.py). No live NERSC access, no real credentials: the
# token is a placeholder the fake backend ignores.
#
# Usage: scripts/smoke_mcp.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PORT="${SMOKE_PORT:-8971}"
BASE_URL="http://127.0.0.1:${PORT}/api/v1"
LOG_DIR="${TMPDIR:-/tmp}/iri-mcp-smoke"
mkdir -p "$LOG_DIR"

PY_CMD=(uv run python)

echo "==> starting fake IRI backend on :${PORT}"
"${PY_CMD[@]}" scripts/fake_iri_http.py --port "$PORT" >"$LOG_DIR/fake.log" 2>&1 &
FAKE_PID=$!
trap 'kill "$FAKE_PID" 2>/dev/null || true' EXIT

echo "==> waiting for backend readiness"
"${PY_CMD[@]}" - "$PORT" <<'EOF'
import sys
import time
import urllib.error
import urllib.request

port = int(sys.argv[1])
for _ in range(100):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/v1/facility", timeout=0.5):
            sys.exit(0)
    except (urllib.error.URLError, OSError):
        time.sleep(0.1)
sys.exit("fake backend did not become ready")
EOF

echo "==> running MCP smoke client against ${BASE_URL}"
export IRI_API_TOKEN="smoke-token"  # placeholder; the fake ignores it
"${PY_CMD[@]}" scripts/smoke_client.py \
    --base-url "$BASE_URL" \
    --allow-submit \
    --allow-fs-write

echo "==> smoke OK (logs in ${LOG_DIR})"