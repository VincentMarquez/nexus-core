from pathlib import Path

from nexus import publish as pub


def test_allowed_paths():
    assert pub._allowed("src/nexus/alive.py", pub.DEFAULT_ALLOW)
    assert pub._allowed("docs/ALIVE.md", pub.DEFAULT_ALLOW)
    assert not pub._allowed(".nexus_state/usage/ledger.jsonl", pub.DEFAULT_ALLOW)
    assert not pub._allowed(".venv/lib/foo", pub.DEFAULT_ALLOW)
    assert not pub._allowed("secrets.db", pub.DEFAULT_ALLOW)


def test_write_improvements_log(tmp_path):
    log = pub.write_improvements_log(
        tmp_path,
        {"goal": "g", "steps": [{"step": "mine", "fetch": 1, "evaluated": 1, "used": 1}]},
    )
    assert log.is_file()
    text = log.read_text(encoding="utf-8")
    assert "Alive improvement log" in text
    assert "mine:" in text
