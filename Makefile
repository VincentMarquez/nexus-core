.PHONY: all install test smoke demo demo-resume demo-judge scoreboard bus dashboard start stop status doctor release-check clean

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

demo:
	. .venv/bin/activate && bash scripts/demo.sh

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

release-check: install test smoke
	@echo "OK — ready to tag a release"

clean:
	. .venv/bin/activate && nexus stop 2>/dev/null || true
	rm -rf .nexus_state .pytest_cache src/*.egg-info dist build
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
