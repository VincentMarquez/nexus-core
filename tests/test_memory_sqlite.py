from nexus.memory_sqlite import SqliteMemory


def test_sqlite_namespace_and_search(tmp_path):
    m = SqliteMemory(tmp_path / "m.db")
    m.seed_demo()
    hits = m.search("checkpoint resume", ns="proj/demo", k=5)
    assert hits
    assert all(h["ns"] == "proj/demo" for h in hits)
    leak = m.search("secret", ns="proj/demo", k=5)
    assert not any("private tenant secret" in h["text"] for h in leak)
