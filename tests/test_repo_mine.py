import json
from pathlib import Path

from nexus import repo_mine as rm
from nexus.github_autonomy import RepoHit


def test_db_insert_and_list(tmp_path):
    conn = rm.connect(tmp_path)
    hit = RepoHit(
        full_name="acme/demo",
        url="https://github.com/acme/demo",
        description="multi-agent orchestration demo",
        stars=12,
        language="Python",
    )
    assert rm.insert_hit(conn, hit) is True
    assert rm.insert_hit(conn, hit) is False  # duplicate
    assert "acme/demo" in rm.known_repos(conn)
    rm.save_eval(conn, "acme/demo", 8.0, 7.5, "nice demo")
    rows = rm.list_entries(conn, min_score=10.0)
    assert any(r["repo"] == "acme/demo" for r in rows)
    conn.close()


def test_heuristic_grade_signals():
    g = rm.heuristic_grade(
        "multi-agent durable orchestration with MCP",
        "pytest README checkpoint resume ollama",
        stars=20,
        language="Python",
    )
    assert 1 <= g["idea"] <= 10
    assert 1 <= g["skill"] <= 10
    assert g["idea"] + g["skill"] >= 10
    assert g["method"] == "heuristic"


def test_digest_repo(tmp_path):
    (tmp_path / "README.md").write_text("# Hello multi-agent\n", encoding="utf-8")
    (tmp_path / "main.py").write_text("def main():\n    pass\n", encoding="utf-8")
    d = rm._digest_repo(tmp_path)
    assert "README" in d or "Hello" in d
