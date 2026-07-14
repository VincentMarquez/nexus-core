#!/usr/bin/env bash
# Real CLI bridge PATTERN — you supply the CLI; we never store keys.
#
# Usage:
#   ./bridges/cli-bridge.sh claude claude --print
#   ./bridges/cli-bridge.sh gpt codex exec --skip-git-repo-check
#
# Arg1 = agent name (file prefix for the bus).
# Rest = CLI command; prompt is passed on stdin.
#
# Auth: CLI login or env vars on YOUR machine only. Never commit secrets.

set -euo pipefail
AGENT="${1:?agent name required}"
shift
if [[ $# -lt 1 ]]; then
  echo "usage: $0 <agent> <cli> [cli-args...]" >&2
  echo "example: $0 claude claude --print" >&2
  exit 2
fi

BRIDGE_DIR="${NEXUS_BRIDGE_DIR:-${TMPDIR:-/tmp}/nexus-bridges}"
mkdir -p "$BRIDGE_DIR"
PROMPT="$BRIDGE_DIR/${AGENT}-prompt.json"
RESPONSE="$BRIDGE_DIR/${AGENT}-response.json"
STATUS="$BRIDGE_DIR/${AGENT}-status.json"
TIMEOUT_S="${NEXUS_CLI_TIMEOUT_S:-180}"

cleanup() {
  echo "{\"status\":\"offline\",\"ts\":$(date +%s000)}" >"$STATUS"
}
trap cleanup EXIT INT TERM

echo "{\"status\":\"online\",\"ts\":$(date +%s000),\"detail\":\"cli\"}" >"$STATUS"
echo "[cli-bridge:$AGENT] online → $*"

while true; do
  if [[ -f "$PROMPT" ]]; then
    echo "{\"status\":\"busy\",\"ts\":$(date +%s000)}" >"$STATUS"
    export PROMPT RESPONSE
    export CLI_TIMEOUT="$TIMEOUT_S"
    # shellcheck disable=SC2068
    python3 - "$PROMPT" "$RESPONSE" "$TIMEOUT_S" "$@" <<'PY'
import json, subprocess, sys, time
prompt_path, response_path, timeout_s, *cmd = sys.argv[1:]
data = json.load(open(prompt_path))
req_id = data.get("id", "")
text_in = data.get("prompt", "")
try:
    proc = subprocess.run(
        cmd,
        input=text_in,
        text=True,
        capture_output=True,
        timeout=float(timeout_s),
    )
    out = (proc.stdout or "").strip()
    if proc.returncode != 0 and not out:
        out = f"[cli-bridge] rc={proc.returncode} stderr={(proc.stderr or '')[:500]}"
    if not out:
        out = "[cli-bridge] empty response"
except Exception as e:
    out = f"[cli-bridge] error: {e}"
json.dump({"id": req_id, "text": out, "ts": time.time()}, open(response_path, "w"))
PY
    rm -f "$PROMPT"
    echo "{\"status\":\"online\",\"ts\":$(date +%s000)}" >"$STATUS"
    echo "[cli-bridge:$AGENT] answered"
  fi
  sleep 0.3
done
