#!/usr/bin/env bash
# GLM-5.2 / colibrì bridge for the NEXUS event bus.
#
# Prefers OpenAI-compatible HTTP (coli serve). Optional CLI fallback.
# No API keys in-repo — paths and ports are yours via env.
#
# Usage:
#   export COLI_OPENAI_BASE=http://127.0.0.1:8000/v1
#   export COLI_OPENAI_MODEL=glm-5.2-colibri
#   ./bridges/colibri-glm.sh glm52
#
# Env:
#   NEXUS_BRIDGE_DIR     shared with bus (default /tmp/nexus-core-bridges)
#   COLI_OPENAI_BASE     e.g. http://127.0.0.1:8000/v1
#   COLI_OPENAI_MODEL    model id reported by serve
#   COLI_OPENAI_KEY      optional bearer (default empty / "local")
#   COLI_CMD             optional fallback: command that reads prompt on stdin

set -euo pipefail
AGENT="${1:-glm52}"
BRIDGE_DIR="${NEXUS_BRIDGE_DIR:-${TMPDIR:-/tmp}/nexus-core-bridges}"
BASE="${COLI_OPENAI_BASE:-http://127.0.0.1:8000/v1}"
MODEL="${COLI_OPENAI_MODEL:-glm-5.2-colibri}"
KEY="${COLI_OPENAI_KEY:-}"
mkdir -p "$BRIDGE_DIR"

PROMPT="$BRIDGE_DIR/${AGENT}-prompt.json"
RESPONSE="$BRIDGE_DIR/${AGENT}-response.json"
STATUS="$BRIDGE_DIR/${AGENT}-status.json"

cleanup() {
  echo "{\"status\":\"offline\",\"ts\":$(date +%s000)}" >"$STATUS"
  echo "[colibri-glm:$AGENT] stopped"
}
trap cleanup EXIT INT TERM

echo "{\"status\":\"online\",\"ts\":$(date +%s000),\"detail\":\"colibri:$MODEL\"}" >"$STATUS"
echo "[colibri-glm:$AGENT] online base=$BASE model=$MODEL"
echo "[colibri-glm:$AGENT] watching $PROMPT"
echo "[colibri-glm:$AGENT] ensure: coli serve  (or set COLI_CMD for CLI fallback)"

while true; do
  if [[ -f "$PROMPT" ]]; then
    echo "{\"status\":\"busy\",\"ts\":$(date +%s000)}" >"$STATUS"
    python3 - "$PROMPT" "$RESPONSE" "$BASE" "$MODEL" "$KEY" "$AGENT" <<'PY'
import json, os, sys, time, urllib.error, urllib.request

prompt_path, response_path, base, model, key, agent = sys.argv[1:7]
data = json.load(open(prompt_path))
req_id = data.get("id", "")
user_in = data.get("prompt", "")

text = None
# --- HTTP OpenAI-compatible chat.completions ---
url = base.rstrip("/") + "/chat/completions"
body = {
    "model": model,
    "messages": [{"role": "user", "content": user_in}],
    "temperature": 0.2,
    "max_tokens": 1024,
}
headers = {"Content-Type": "application/json"}
if key:
    headers["Authorization"] = f"Bearer {key}"
try:
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), headers=headers, method="POST"
    )
    with urllib.request.urlopen(req, timeout=600) as r:
        payload = json.loads(r.read().decode())
    text = (
        payload.get("choices", [{}])[0]
        .get("message", {})
        .get("content")
        or payload.get("choices", [{}])[0].get("text")
        or ""
    ).strip()
except Exception as e:
    http_err = f"[colibri-glm:{agent}] HTTP error: {e}"
    # --- optional CLI fallback ---
    cmd = os.environ.get("COLI_CMD")
    if cmd:
        import subprocess

        try:
            p = subprocess.run(
                cmd,
                shell=True,
                input=user_in,
                text=True,
                capture_output=True,
                timeout=600,
            )
            text = (p.stdout or "").strip() or http_err + f" | CLI rc={p.returncode}"
        except Exception as e2:
            text = http_err + f" | CLI error: {e2}"
    else:
        text = (
            http_err
            + " | start coli serve or set COLI_OPENAI_BASE / COLI_CMD"
        )

if not text:
    text = f"[colibri-glm:{agent}] empty response"
json.dump({"id": req_id, "text": text, "ts": time.time()}, open(response_path, "w"))
print(f"[colibri-glm:{agent}] answered id={req_id} chars={len(text)}")
PY
    rm -f "$PROMPT"
    echo "{\"status\":\"online\",\"ts\":$(date +%s000),\"detail\":\"colibri:$MODEL\"}" >"$STATUS"
  fi
  sleep 0.3
done
