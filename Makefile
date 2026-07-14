.PHONY: install test smoke demo demo-resume demo-judge scoreboard bus dashboard release-check clean

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

bus:
	cd bridge && NEXUS_STATE_DIR=../.nexus_state npm start

dashboard:
	@echo "Start the bus, then open: http://127.0.0.1:3099/dashboard"
	@echo "  make bus"

release-check: install test smoke
	@echo "OK — ready to tag a release"

clean:
	rm -rf .nexus_state .pytest_cache src/*.egg-info dist build
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
