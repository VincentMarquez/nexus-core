#!/usr/bin/env bash
# Real CLI bridge — file-drop protocol for the NEXUS bus.
#
# Usage:
#   ./bridges/cli-bridge.sh claude claude --print --bare --model fable --effort max
#   ./bridges/cli-bridge.sh gpt codex exec --skip-git-repo-check -s workspace-write ...
#
# Arg1 = agent name (file prefix for the bus).
# Rest = CLI command. Prompt is passed on stdin by default; set
# NEXUS_CLI_PROMPT_MODE=arg to append the prompt as the last CLI argument
# (more reliable for some Codex versions).
#
# Auth: CLI login or env vars on YOUR machine only. Never commit secrets.

set -euo pipefail
AGENT="${1:?agent name required}"
shift
if [[ $# -lt 1 ]]; then
  echo "usage: $0 <agent> <cli> [cli-args...]" >&2
  echo "example: $0 claude claude --print --bare" >&2
  exit 2
fi

BRIDGE_DIR="${NEXUS_BRIDGE_DIR:-${TMPDIR:-/tmp}/nexus-bridges}"
mkdir -p "$BRIDGE_DIR"
PROMPT="$BRIDGE_DIR/${AGENT}-prompt.json"
RESPONSE="$BRIDGE_DIR/${AGENT}-response.json"
STATUS="$BRIDGE_DIR/${AGENT}-status.json"
TIMEOUT_S="${NEXUS_CLI_TIMEOUT_S:-600}"
PROMPT_MODE="${NEXUS_CLI_PROMPT_MODE:-stdin}"  # stdin | arg

cleanup() {
  echo "{\"status\":\"offline\",\"ts\":$(date +%s000)}" >"$STATUS"
}
trap cleanup EXIT INT TERM

echo "{\"status\":\"online\",\"ts\":$(date +%s000),\"detail\":\"cli\"}" >"$STATUS"
echo "[cli-bridge:$AGENT] online mode=$PROMPT_MODE timeout=${TIMEOUT_S}s → $*"

while true; do
  if [[ -f "$PROMPT" ]]; then
    echo "{\"status\":\"busy\",\"ts\":$(date +%s000)}" >"$STATUS"
    export PROMPT RESPONSE
    export CLI_TIMEOUT="$TIMEOUT_S"
    export NEXUS_CLI_PROMPT_MODE="$PROMPT_MODE"
    # shellcheck disable=SC2068
    python3 - "$PROMPT" "$RESPONSE" "$TIMEOUT_S" "$PROMPT_MODE" "$@" <<'PY'
import json, os, subprocess, sys, time
from pathlib import Path

prompt_path, response_path, timeout_s, prompt_mode, *cmd = sys.argv[1:]
data = json.load(open(prompt_path, encoding="utf-8"))
req_id = data.get("id", "")
text_in = data.get("prompt", "") or ""

def write_response(text: str) -> None:
    """Atomic write so the bus never reads a partial JSON file."""
    out = {"id": req_id, "text": text, "ts": time.time()}
    path = Path(response_path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(out), encoding="utf-8")
    tmp.replace(path)

try:
    run_cmd = list(cmd)
    # Codex: prefer prompt as last arg (avoids stdin "Reading additional input")
    if prompt_mode == "arg" or (
        prompt_mode == "auto"
        and run_cmd
        and Path(run_cmd[0]).name in ("codex", "codex.exe")
    ):
        run_cmd = run_cmd + [text_in]
        inp = None
    else:
        inp = text_in

    proc = subprocess.run(
        run_cmd,
        input=inp,
        text=True,
        capture_output=True,
        timeout=float(timeout_s),
        env=os.environ.copy(),
    )
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    if proc.returncode != 0 and not out:
        out = f"[cli-bridge] rc={proc.returncode} stderr={err[:800]}"
    elif not out and err:
        # some CLIs put useful text on stderr
        out = err[-4000:]
    if not out:
        out = "[cli-bridge] empty response"
except subprocess.TimeoutExpired:
    out = f"[cli-bridge] timeout after {timeout_s}s"
except Exception as e:
    out = f"[cli-bridge] error: {e}"

write_response(out)
# remove prompt only after response is durable
try:
    os.remove(prompt_path)
except OSError:
    pass
PY
    # prompt already removed inside python when successful; ensure cleanup
    rm -f "$PROMPT" 2>/dev/null || true
    echo "{\"status\":\"online\",\"ts\":$(date +%s000)}" >"$STATUS"
    echo "[cli-bridge:$AGENT] answered"
  fi
  sleep 0.25
done
