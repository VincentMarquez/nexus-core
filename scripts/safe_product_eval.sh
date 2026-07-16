#!/usr/bin/env bash
# Safe evaluate of GitHub product code WITHOUT touching the live lab NEXUS.
#
# Layers:
#   Lab (live):     ~/Desktop/research   — leave running; do not overwrite
#   Product (live): ~/nexus-core         — your working product tree
#   Staging:        ~/nexus-core-staging — clean origin/main worktree for tests
#
# Usage:
#   bash scripts/safe_product_eval.sh              # fetch + test staging
#   bash scripts/safe_product_eval.sh --compare    # also list best modules
#   bash scripts/safe_product_eval.sh --promote    # ONLY after green: merge staging→product main
#
set -euo pipefail

PRODUCT="${NEXUS_PRODUCT:-$HOME/nexus-core}"
STAGING="${NEXUS_STAGING:-$HOME/nexus-core-staging}"
# Lab is never written by this script — path is for logging / operator awareness only.
LAB="${NEXUS_LAB:-$HOME/Desktop/Projects/research}"
if [[ ! -d "$LAB" && -d "$HOME/Desktop/research" ]]; then
  LAB="$HOME/Desktop/research"
fi
PROMOTE=0
COMPARE=0

for a in "$@"; do
  case "$a" in
    --promote) PROMOTE=1 ;;
    --compare) COMPARE=1 ;;
    -h|--help)
      sed -n '2,20p' "$0"
      exit 0
      ;;
  esac
done

log() { echo "→ $*"; }

# ---------------------------------------------------------------------------
# 1) Ensure staging worktree = GitHub origin/main (isolated)
# ---------------------------------------------------------------------------
cd "$PRODUCT"
git fetch origin --quiet
if [[ ! -d "$STAGING/.git" ]] && [[ ! -f "$STAGING/.git" ]]; then
  log "creating staging worktree at $STAGING"
  git worktree add "$STAGING" origin/main
else
  log "updating staging worktree to origin/main"
  # worktree may be detached
  git -C "$STAGING" fetch origin --quiet
  git -C "$STAGING" checkout --detach origin/main
fi

HEAD=$(git -C "$STAGING" rev-parse --short HEAD)
log "staging HEAD = $HEAD (GitHub main)"
log "product HEAD = $(git -C "$PRODUCT" rev-parse --short HEAD)"
log "lab path     = $LAB (NOT modified by this script)"

# ---------------------------------------------------------------------------
# 2) Run product test suite ONLY in staging (never lab)
# ---------------------------------------------------------------------------
log "running pytest in staging (isolated state dir)…"
export NEXUS_PROJECT_ROOT="$STAGING"
export NEXUS_STATE_DIR="$STAGING/.nexus_state_eval"
mkdir -p "$NEXUS_STATE_DIR"
cd "$STAGING"
export PYTHONPATH="$STAGING/src${PYTHONPATH:+:$PYTHONPATH}"

set +e
python3 -m pytest tests/ -q --tb=line 2>&1 | tee "$NEXUS_STATE_DIR/eval_pytest.log" | tail -20
RC=${PIPESTATUS[0]}
set -e

if [[ $RC -ne 0 ]]; then
  log "FAIL: staging tests exit $RC — do NOT promote"
  log "log: $NEXUS_STATE_DIR/eval_pytest.log"
  exit "$RC"
fi
log "PASS: staging tests green"

# smoke CLI
python3 -m nexus.cli doctor >/dev/null 2>&1 && log "PASS: nexus doctor" || log "WARN: doctor non-zero (ok offline)"
python3 -c "from nexus.engine import DurableEngine; from nexus.agents import AgentPanel; print('PASS: imports')" 

# ---------------------------------------------------------------------------
# 3) Optional: show best modules to port into lab (docs only)
# ---------------------------------------------------------------------------
if [[ $COMPARE -eq 1 ]]; then
  log "=== best product modules to use from lab (import, don't copy whole tree) ==="
  cat <<'EOF'
  PYTHONPATH=~/nexus-core/src
  from nexus.engine import DurableEngine
  from nexus.agents import AgentPanel
  from nexus.grok_worker import grok_grade, grok_hard_improve
  from nexus.repo_mine import run_pipeline
  from nexus.alive import cycle_once

  Best "keep" surfaces for production quality:
    - src/nexus/engine.py      durable checkpoints, journal, task ops
    - src/nexus/agents.py      multi-vendor + timeout fallback
    - src/nexus/cli.py         nexus task / platforms / start
    - src/nexus/persist.py     atomic writes
    - src/nexus/grok_worker.py headless Grok grade/apply
    - scripts/multi_vendor_live.py
    - fixtures/                required for CI tests

  Lab stays the boss of:
    - Desktop/research/run.py, EEG, bridges, ops systemd units
EOF
fi

# ---------------------------------------------------------------------------
# 4) Promote only if requested AND tests green
# ---------------------------------------------------------------------------
if [[ $PROMOTE -eq 1 ]]; then
  log "PROMOTE: fast-forward product main to origin/main (lab untouched)"
  cd "$PRODUCT"
  if [[ -n $(git status --porcelain | grep -v '^[?][?]') ]]; then
    log "ERROR: product tree has uncommitted changes — commit/stash first"
    git status -sb
    exit 2
  fi
  git merge --ff-only origin/main
  log "product main now $(git rev-parse --short HEAD)"
  log "re-run tests on product:"
  PYTHONPATH="$PRODUCT/src" python3 -m pytest tests/ -q --tb=line | tail -5
fi

log "done. Lab NEXUS ($LAB) was not modified."
log "To use product from lab without merge:"
log "  export PYTHONPATH=$PRODUCT/src"
log "  nexus …   # if installed editable from product"
exit 0
