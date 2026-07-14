#!/usr/bin/env bash
# Killer demo: crash mid-task → resume → completed.
# Usage: ./scripts/demo.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
# shellcheck disable=SC1091
source .venv/bin/activate 2>/dev/null || { python3 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]" -q; }

TASK_ID="killer-demo-$$"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

bold() { printf '\n\033[1m%s\033[0m\n' "$*"; }
dim() { printf '\033[2m%s\033[0m\n' "$*"; }
ok() { printf '\033[32m✓ %s\033[0m\n' "$*"; }

if [[ "${1:-}" == "--resume-only" ]]; then
  bold "Resuming last killer-demo task…"
  ls -1 .nexus_state/tasks/killer-demo-*.json 2>/dev/null | tail -1 || true
  exit 0
fi

bold "NEXUS Core — crash-safe multi-agent demo"
dim "Problem: agent pipelines die mid-run and lose work."
dim "Demo: run 3 steps → simulate crash → resume → finish 10/10."

rm -f ".nexus_state/tasks/${TASK_ID}.json" 2>/dev/null || true
mkdir -p .nexus_state/tasks results

bold "1) Start task (stop after step 3 — simulating kill -9)"
python examples/run_demo_task.py --task-id "$TASK_ID" --kill-after 3
STATUS=$(python -c "import json;print(json.load(open('.nexus_state/tasks/${TASK_ID}.json'))['status'])")
STEP=$(python -c "import json;print(json.load(open('.nexus_state/tasks/${TASK_ID}.json'))['current_step'])")
ok "checkpoint saved: status=$STATUS step=$STEP/10"

bold "2) Process 'died'. Work is on disk:"
python -c "import json; t=json.load(open('.nexus_state/tasks/${TASK_ID}.json')); print('  task_id:', t['task_id']); print('  status:', t['status']); print('  steps done:', sorted(t.get('outputs',{}).keys()))"

bold "3) Resume from checkpoint"
python examples/run_demo_task.py --resume "$TASK_ID"
STATUS=$(python -c "import json;print(json.load(open('.nexus_state/tasks/${TASK_ID}.json'))['status'])")
STEP=$(python -c "import json;print(json.load(open('.nexus_state/tasks/${TASK_ID}.json'))['current_step'])")
ok "final: status=$STATUS step=$STEP/10"

bold "4) Artifact"
ART="results/${TASK_ID}_artifact.txt"
if [[ -f "$ART" ]]; then
  ok "wrote $ART → $(cat "$ART" | tr -d '\n')"
else
  # mock path may vary
  ls -1 results/*artifact* 2>/dev/null | tail -3 || true
fi

bold "Done."
echo
echo "  That is the whole pitch:"
echo "  multi-agent tasks that resume after a crash,"
echo "  with a judge that checks real success criteria."
echo
echo "  Repo: https://github.com/VincentMarquez/nexus-core"
echo "  Next: make demo-judge | make bus | docs/SHOW_HN.md"
