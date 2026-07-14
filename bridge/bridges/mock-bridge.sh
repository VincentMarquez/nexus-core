#!/usr/bin/env bash
# Mock agent bridge — no API keys, no real LLM.
# Speaks the file-drop protocol expected by bridge/server.js
#
# Usage:  ./bridges/mock-bridge.sh [agent_name]
# Env:    NEXUS_BRIDGE_DIR  (must match the bus)

set -euo pipefail
AGENT="${1:-claude}"
BRIDGE_DIR="${NEXUS_BRIDGE_DIR:-${TMPDIR:-/tmp}/nexus-bridges}"
mkdir -p "$BRIDGE_DIR"

PROMPT="$BRIDGE_DIR/${AGENT}-prompt.json"
RESPONSE="$BRIDGE_DIR/${AGENT}-response.json"
STATUS="$BRIDGE_DIR/${AGENT}-status.json"

cleanup() {
  echo "{\"status\":\"offline\",\"ts\":$(date +%s000)}" >"$STATUS"
  echo "[mock-bridge:$AGENT] stopped"
}
trap cleanup EXIT INT TERM

echo "{\"status\":\"online\",\"ts\":$(date +%s000),\"detail\":\"mock\"}" >"$STATUS"
echo "[mock-bridge:$AGENT] online — watching $PROMPT"

while true; do
  if [[ -f "$PROMPT" ]]; then
    echo "{\"status\":\"busy\",\"ts\":$(date +%s000)}" >"$STATUS"
    python3 - "$PROMPT" "$RESPONSE" "$AGENT" <<'PY'
import json, sys, time
prompt_path, response_path, agent = sys.argv[1:4]
data = json.load(open(prompt_path))
req_id = data.get("id", "")
prompt = (data.get("prompt") or "")[:500]
text = f"[mock:{agent}] echo: {prompt}"
json.dump({"id": req_id, "text": text, "ts": time.time()}, open(response_path, "w"))
print(f"[mock-bridge:{agent}] answered id={req_id}")
PY
    rm -f "$PROMPT"
    echo "{\"status\":\"online\",\"ts\":$(date +%s000),\"detail\":\"mock\"}" >"$STATUS"
  fi
  sleep 0.3
done
