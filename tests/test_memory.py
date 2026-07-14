from nexus.memory import MemorySpine


def test_namespace_isolation():
    m = MemorySpine.demo()
    hits = m.search("secret", ns="proj/demo", k=5)
    assert all(h["ns"] == "proj/demo" for h in hits)
    assert not any("private tenant secret" in h["text"] for h in hits)


def test_search_finds_durable():
    m = MemorySpine.demo()
    hits = m.search("checkpoint resume", ns="proj/demo", k=3)
    assert hits
    assert any("Durable" in h["text"] or "checkpoint" in h["text"].lower() for h in hits)
