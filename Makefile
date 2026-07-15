.PHONY: all install test smoke eval-samples demo demo-all demo-all-quick demo-resume demo-judge scoreboard bus dashboard start stop status doctor release-check clean grade-validate mcp-smoke board-sync-gaps test-quality

# Default: zero-config bootstrap + automatic start with agents
all: run

run:
	@bash ./run

install:
	python3 -m venv .venv || true
	. .venv/bin/activate && pip install -e ".[dev]" -q

test:
	. .venv/bin/activate && pytest -q

smoke:
	. .venv/bin/activate && python evals/smoke.py

# First-apply quality gates (offline fixtures only — no live Grok API)
# P0.3 grade schema + claims; P0.4 MCP SQLite/FTS evidence search
grade-validate:
	. .venv/bin/activate && PYTHONPATH=src python -c "\
from nexus.evidence_fts import grade_validate_fixtures; \
import json, sys; \
r = grade_validate_fixtures('.'); \
print(json.dumps(r, indent=2)); \
sys.exit(0 if r.get('ok') else 1)"

mcp-smoke:
	. .venv/bin/activate && PYTHONPATH=src python -c "\
from nexus.evidence_fts import smoke_search; \
import json, sys; \
r = smoke_search('.'); \
print(json.dumps(r, indent=2)); \
sys.exit(0 if r.get('ok') else 1)"

# Board signal → PrincipledStop gaps (operator gate regression)
board-sync-gaps:
	. .venv/bin/activate && PYTHONPATH=src python -c "\
from nexus.apply_select import smoke_board_sync; \
import json, sys; \
r = smoke_board_sync('.'); \
print(json.dumps(r, indent=2, default=str)); \
sys.exit(0 if r.get('ok') else 1)"

test-quality: grade-validate mcp-smoke board-sync-gaps
	@echo "OK — grade-validate + mcp-smoke + board-sync-gaps"

# Offline sample MCP scenario packs (fixtures/ → .nexus_state/; CI-safe)
eval-samples:
	. .venv/bin/activate && PYTHONPATH=src python -m nexus.cli eval smoke \
		--install-samples --tag sample --no-builtin --no-export

# Classic: crash → resume only
demo:
	. .venv/bin/activate && bash scripts/demo.sh

# Full product showcase (use this for videos / visitors)
demo-all:
	. .venv/bin/activate && bash scripts/demo_showcase.sh

demo-all-quick:
	. .venv/bin/activate && bash scripts/demo_showcase.sh --quick

demo-resume:
	. .venv/bin/activate && bash scripts/demo.sh --resume-only

demo-judge:
	. .venv/bin/activate && python examples/demo_judge_vs_presence.py

scoreboard:
	. .venv/bin/activate && python evals/scoreboard.py

# Fully automatic: bus + dashboard + Ollama + CLI agents when installed
start:
	. .venv/bin/activate && nexus start --yes

# Explicit aliases (same as start now; kept for docs / old habits)
start-cli:
	. .venv/bin/activate && nexus start --yes

start-mock:
	. .venv/bin/activate && nexus start --yes --no-cli

stop:
	. .venv/bin/activate && nexus stop

status:
	. .venv/bin/activate && nexus status

doctor:
	. .venv/bin/activate && nexus doctor

bus:
	cd bridge && NEXUS_STATE_DIR=../.nexus_state npm start

dashboard:
	@echo "Run: ./run   (opens dashboard automatically)"
	@echo "Or:  http://127.0.0.1:3099/dashboard"

mcp-http:
	. .venv/bin/activate && nexus mcp --http --port 8765

docs-serve:
	. .venv/bin/activate && pip install -q mkdocs-material && mkdocs serve

docs-build:
	. .venv/bin/activate && pip install -q mkdocs-material && mkdocs build --strict

release-check: install test smoke test-quality
	@echo "OK — ready to tag a release"

clean:
	. .venv/bin/activate && nexus stop 2>/dev/null || true
	rm -rf .nexus_state .pytest_cache src/*.egg-info dist build
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
