import time

from nexus.memory_sqlite import SqliteMemory


def test_sqlite_namespace_and_search(tmp_path):
    m = SqliteMemory(tmp_path / "m.db")
    m.seed_demo()
    hits = m.search("checkpoint resume", ns="proj/demo", k=5)
    assert hits
    assert all(h["ns"] == "proj/demo" for h in hits)
    leak = m.search("secret", ns="proj/demo", k=5)
    assert not any("private tenant secret" in h["text"] for h in leak)


def test_sqlite_decay_prefers_fresh_chunks(tmp_path):
    """Decay-aware ranking (openclaw-hawkins pattern): fresher wins at same token score."""
    now = time.time()
    m = SqliteMemory(tmp_path / "decay.db", decay_half_life_days=7.0)
    m.add_text(
        "agent orchestration durable workflow alpha",
        ns="proj/demo",
        id="old",
        ts=now - 30 * 86400,
    )
    m.add_text(
        "agent orchestration durable workflow beta",
        ns="proj/demo",
        id="new",
        ts=now,
    )
    hits = m.search("agent orchestration durable", ns="proj/demo", k=2)
    assert len(hits) == 2
    assert hits[0]["id"] == "new"
    assert hits[0]["score"] > hits[1]["score"]
    # ts surfaced for operators
    assert hits[0].get("ts") is not None


def test_sqlite_ts_migration_on_legacy_schema(tmp_path):
    import sqlite3

    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(str(path))
    conn.execute(
        """
        CREATE TABLE chunks (
          id TEXT PRIMARY KEY,
          ns TEXT NOT NULL,
          kind TEXT NOT NULL DEFAULT 'doc',
          source TEXT NOT NULL DEFAULT '',
          text TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "INSERT INTO chunks(id, ns, kind, source, text) VALUES (?,?,?,?,?)",
        ("c1", "proj/demo", "doc", "", "legacy checkpoint resume row"),
    )
    conn.commit()
    conn.close()
    m = SqliteMemory(path)
    hits = m.search("checkpoint", ns="proj/demo", k=3)
    assert hits
    assert hits[0]["id"] == "c1"
