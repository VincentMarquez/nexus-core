from nexus.cascade import CascadeIndex


def test_prompt_block_mentions_laws():
    idx = CascadeIndex.demo()
    block = idx.prompt_block()
    assert "CASCADE" in block
    assert "engine" in idx.branch("engine").lower() or "engine" in block
