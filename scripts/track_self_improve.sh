#!/usr/bin/env bash
# Track the self-improve *spine* only — not the whole dirty product tree.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

SPINE=(
  src/nexus/alive.py
  src/nexus/unified_pipeline.py
  src/nexus/idea_portfolio.py
  src/nexus/github_autonomy.py
  src/nexus/repo_mine.py
  src/nexus/paper_improve.py
  src/nexus/mcp_server.py
  src/nexus/tool_catalog.py
  src/nexus/self_improve
  tests/test_usage_alive.py
  tests/test_paper_improve.py
  docs/self-improve
  docs/SELF_IMPROVE.md
  scripts/track_self_improve.sh
)

echo "=== nexus-core self-improve tracker ==="
echo "repo: $ROOT"
echo "branch: $(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?')"
echo "remote: $(git rev-parse --abbrev-ref --symbolic-full-name @{u} 2>/dev/null || echo '(no upstream)')"
echo "HEAD: $(git log -1 --oneline 2>/dev/null || echo '?')"
echo
echo "--- map docs ---"
echo "  docs/self-improve/README.md   (start here)"
echo "  docs/self-improve/MAP.md      (one-page layout)"
echo "  docs/SELF_IMPROVE.md          (root pointer)"
echo
echo "--- spine git status ---"
git status -sb -- "${SPINE[@]}" 2>/dev/null || true
echo
echo "--- untracked / modified spine files ---"
dirty=0
for p in "${SPINE[@]}"; do
  if [[ ! -e "$p" ]]; then
    printf '  MISSING  %s\n' "$p"
    dirty=1
    continue
  fi
  # directory: show if any path under it is dirty
  if [[ -d "$p" ]]; then
    if ! git diff --quiet HEAD -- "$p" 2>/dev/null || \
       [[ -n "$(git ls-files --others --exclude-standard -- "$p")" ]]; then
      printf '  DIRTY    %s/\n' "$p"
      dirty=1
    else
      printf '  clean    %s/\n' "$p"
    fi
  else
    if ! git ls-files --error-unmatch "$p" >/dev/null 2>&1; then
      printf '  NEW      %s\n' "$p"
      dirty=1
    elif ! git diff --quiet HEAD -- "$p" 2>/dev/null; then
      printf '  MODIFIED %s\n' "$p"
      dirty=1
    else
      printf '  clean    %s\n' "$p"
    fi
  fi
done
echo
if [[ $dirty -eq 0 ]]; then
  echo "spine: all tracked and clean vs HEAD"
else
  echo "spine: has local changes (see above)"
  echo
  echo "commit only the spine (example):"
  echo "  git add \\"
  for p in "${SPINE[@]}"; do
    echo "    $p \\"
  done
  echo "  # then: git commit -m 'feat(self-improve): portfolio + map + facade'"
fi
echo
echo "--- runtime artifacts (local, not source) ---"
for f in docs/LATEST_IMPLEMENT_SUMMARY.md docs/LATEST_IDEA_PORTFOLIO.md \
         .nexus_state/alive.json .nexus_state/LAST_IMPLEMENT_SUMMARY.json; do
  if [[ -e "$f" ]]; then
    printf '  present  %s\n' "$f"
  else
    printf '  absent   %s\n' "$f"
  fi
done
echo
echo "--- lab remote control (separate tree) ---"
LAB="${NEXUS_LAB:-`${NEXUS_LAB_ROOT:-~/lab}`}"
if [[ -d "$LAB" ]]; then
  echo "  $LAB"
  for f in bridge/server.js bridge/product_control.js \
           src/ProductSelfImprove.jsx src/CerfMultiAgent.jsx \
           docs/self-improve/README.md; do
    if [[ -e "$LAB/$f" ]]; then
      printf '  present  %s\n' "$f"
    else
      printf '  absent   %s\n' "$f"
    fi
  done
else
  echo "  (lab not found at $LAB — set NEXUS_LAB=...)"
fi
