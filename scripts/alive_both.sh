#!/usr/bin/env bash
# Run lab infrastructure + product self-improve → GitHub in two modes.
#
#   ./scripts/alive_both.sh setup     # integrate + enable apply/push config
#   ./scripts/alive_both.sh once      # one product cycle (may push if enabled)
#   ./scripts/alive_both.sh watch     # continuous product alive
#   ./scripts/alive_both.sh lab       # remind how to start research run.py
#
set -euo pipefail
PRODUCT="${NEXUS_PRODUCT_ROOT:-$HOME/nexus-core}"
LAB="${NEXUS_LAB_ROOT:-$HOME/Desktop/research}"
# shellcheck disable=SC1091
source "$PRODUCT/.venv/bin/activate" 2>/dev/null || true
export PATH="$PRODUCT/.venv/bin:$HOME/.local/bin:$PATH"
export NEXUS_PROJECT_ROOT="${NEXUS_PROJECT_ROOT:-$PRODUCT}"
export OLLAMA_HOST="${OLLAMA_HOST:-http://127.0.0.1:11434}"
export OLLAMA_MODEL="${OLLAMA_MODEL:-gemma4:26b}"

cmd="${1:-help}"

case "$cmd" in
  setup)
    bash "$PRODUCT/scripts/integrate_research.sh"
    nexus usage set --daily "${NEXUS_DAILY_TOKENS:-500000}" --monthly "${NEXUS_MONTHLY_TOKENS:-8000000}"
    nexus alive init \
      --goal "${NEXUS_ALIVE_GOAL:-improve multi-agent durability, demos, mine→github}" \
      -q "${NEXUS_ALIVE_QUERY:-multi agent durable orchestration}" \
      --repo "${NEXUS_ALIVE_REPO:-VincentMarquez/nexus-core}" \
      --apply --self-approve --push-github
    echo
    echo "Config written. Defaults are NOW set to apply+self_approve+push_github."
    echo "Run: $0 once"
    ;;
  once)
    cd "$PRODUCT"
    nexus alive once
    echo
    echo "Check: git -C $PRODUCT log -1 --oneline"
    echo "       less $PRODUCT/.nexus_state/alive_state.json"
    ;;
  watch)
    cd "$PRODUCT"
    exec nexus alive watch --interval "${2:-3600}"
    ;;
  lab)
    echo "Start lab in another terminal:"
    echo "  cd $LAB && python3 run.py"
    echo
    echo "Product self-improve (this tree → GitHub):"
    echo "  $0 once   |  $0 watch"
    ;;
  help|*)
    cat <<EOF
Usage: $0 setup|once|watch|lab

  setup  — link lab+product, enable apply + self_approve + push_github
  once   — one self-improve cycle (mine → tests → commit → push if green)
  watch  — continuous product alive loop
  lab    — print how to run research run.py alongside

Env:
  NEXUS_PRODUCT_ROOT  (default ~/nexus-core)
  NEXUS_LAB_ROOT      (default ~/Desktop/research)
  OLLAMA_MODEL        (default gemma4:26b)
EOF
    ;;
esac
