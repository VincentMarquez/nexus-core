#!/usr/bin/env bash
# Local LLM bridge via Ollama HTTP API — no cloud keys.
#
# Requires: ollama running (default http://127.0.0.1:11434)
# Usage:
#   ./bridges/ollama-http.sh [agent_name] [model]
#   ./bridges/ollama-http.sh local gemma2
#
# Env:
#   NEXUS_BRIDGE_DIR   must match the bus (default: $TMPDIR/nexus-bridges)
#   OLLAMA_HOST        default http://127.0.0.1:11434
#   OLLAMA_MODEL       default gemma2 (or second CLI arg)

set -euo pipefail
AGENT="${1:-local}"
MODEL="${2:-${OLLAMA_MODEL:-gemma2}}"
HOST="${OLLAMA_HOST:-http://127.0.0.1:11434}"
BRIDGE_DIR="${NEXUS_BRIDGE_DIR:-${TMPDIR:-/tmp}/nexus-bridges}"
mkdir -p "$BRIDGE_DIR"

PROMPT="$BRIDGE_DIR/${AGENT}-prompt.json"
RESPONSE="$BRIDGE_DIR/${AGENT}-response.json"
STATUS="$BRIDGE_DIR/${AGENT}-status.json"

cleanup() {
  echo "{\"status\":\"offline\",\"ts\":$(date +%s000)}" >"$STATUS"
  echo "[ollama-http:$AGENT] stopped"
}
trap cleanup EXIT INT TERM

# quick reachability check
if ! curl -sf --max-time 2 "$HOST/api/tags" >/dev/null; then
  echo "[ollama-http] ERROR: cannot reach $HOST — is ollama running?" >&2
  echo "  try: ollama serve   &&   ollama pull $MODEL" >&2
  exit 1
fi

echo "{\"status\":\"online\",\"ts\":$(date +%s000),\"detail\":\"ollama:$MODEL\"}" >"$STATUS"
echo "[ollama-http:$AGENT] online model=$MODEL host=$HOST"
echo "[ollama-http:$AGENT] watching $PROMPT"

while true; do
  if [[ -f "$PROMPT" ]]; then
    echo "{\"status\":\"busy\",\"ts\":$(date +%s000)}" >"$STATUS"
    python3 - "$PROMPT" "$RESPONSE" "$HOST" "$MODEL" "$AGENT" <<'PY'
import json, sys, time, urllib.error, urllib.request

prompt_path, response_path, host, model, agent = sys.argv[1:6]
data = json.load(open(prompt_path))
req_id = data.get("id", "")
user_in = data.get("prompt", "")

payload = {
    "model": model,
    "prompt": user_in,
    "stream": False,
    # keep answers short for orchestration
    "options": {"temperature": 0.2, "num_predict": 512},
}
url = host.rstrip("/") + "/api/generate"
try:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=300) as r:
        body = json.loads(r.read().decode())
    text = (body.get("response") or "").strip() or f"[ollama:{agent}] empty response"
except Exception as e:
    text = f"[ollama:{agent}] error: {e}"

json.dump({"id": req_id, "text": text, "ts": time.time()}, open(response_path, "w"))
print(f"[ollama-http:{agent}] answered id={req_id} chars={len(text)}")
PY
    rm -f "$PROMPT"
    echo "{\"status\":\"online\",\"ts\":$(date +%s000),\"detail\":\"ollama:$MODEL\"}" >"$STATUS"
  fi
  sleep 0.3
done
