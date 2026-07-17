"""S03: implement ledger + portfolio cooldown."""

from __future__ import annotations

import time
from pathlib import Path

from nexus import idea_portfolio as ip


def test_append_and_cooled_keys(tmp_path: Path):
    ip.append_implement_ledger(
        tmp_path,
        idea_id="wshobson/agents",
        source="github",
        ok=True,
        cycle_id="c1",
        seed="wshobson/agents",
    )
    ip.append_implement_ledger(
        tmp_path,
        idea_id="arxiv:2602.03411v2",
        source="arxiv",
        ok=True,
        cycle_id="c1",
    )
    # failed should not cool when only_ok=True
    ip.append_implement_ledger(
        tmp_path,
        idea_id="org/other",
        source="github",
        ok=False,
        seed="org/other",
    )
    cooled = ip.cooled_keys(tmp_path, cooldown_days=7.0)
    assert "wshobson/agents" in cooled
    assert "arxiv:2602.03411v2" in cooled
    assert "org/other" not in cooled


def test_order_with_cooldown_puts_hot_first():
    items = [
        {"id": "wshobson/agents", "source": "github", "score": 16},
        {"id": "other/repo", "source": "github", "score": 15},
    ]
    ordered = ip.order_with_cooldown(items, {"wshobson/agents"})
    assert ordered[0]["id"] == "other/repo"
    assert ordered[1]["id"] == "wshobson/agents"


def test_select_portfolio_demotes_cooled_github():
    arxiv = [
        {"id": "arxiv:2602.03411v2", "score": 9.0, "source": "arxiv"},
        {"id": "arxiv:2606.07412v1", "score": 8.0, "source": "arxiv"},
        {"id": "arxiv:2501.00001v1", "score": 7.0, "source": "arxiv"},
    ]
    github = [
        {"id": "wshobson/agents", "score": 16.0, "source": "github"},
        {"id": "builderz-labs/mission-control", "score": 15.0, "source": "github"},
        {"id": "IBM/AssetOpsBench", "score": 14.0, "source": "github"},
    ]
    novels = [
        {
            "id": "novel:arxiv:2602.03411v2+wshobson/agents",
            "score": 8.5,
            "source": "cross_pattern",
            "arxiv_id": "arxiv:2602.03411v2",
            "github_id": "wshobson/agents",
        }
    ]
    cooled = {"wshobson/agents"}
    port = ip.select_portfolio(
        arxiv,
        github,
        novels,
        max_ideas=6,
        max_per_arxiv_seed=2,
        min_distinct_arxiv=2,
        cooled_ids=cooled,
    )
    ids = [p["id"] for p in port]
    # required_github should prefer non-cooled
    required_gh = [p for p in port if p.get("selected_as") == "required_github"]
    assert required_gh
    assert required_gh[0]["id"] != "wshobson/agents"
    assert "builderz-labs/mission-control" in ids or "IBM/AssetOpsBench" in ids
    # wshobson may still appear only as cooldown_reuse fill, not required
    for p in port:
        if p["id"] == "wshobson/agents":
            assert p.get("selected_as") != "required_github" or p.get("cooldown_reuse")


def test_select_portfolio_fail_open_when_only_cooled_github():
    arxiv = [{"id": "arxiv:1", "score": 9.0, "source": "arxiv"}]
    github = [{"id": "only/repo", "score": 16.0, "source": "github"}]
    port = ip.select_portfolio(
        arxiv,
        github,
        [],
        min_arxiv=1,
        min_github=1,
        max_ideas=4,
        cooled_ids={"only/repo"},
    )
    assert any(p["id"] == "only/repo" for p in port)
    gh = [p for p in port if p.get("source") == "github"]
    assert gh and gh[0].get("cooldown_reuse") is True


def test_bootstrap_from_alive_state(tmp_path: Path):
    state = {
        "ts": time.time(),
        "steps": [
            {
                "step": "implement",
                "results": [
                    {"id": "wshobson/agents", "source": "github", "ok": True},
                    {"id": "arxiv:1", "source": "arxiv", "ok": True},
                ],
            }
        ],
    }
    p = tmp_path / ".nexus_state"
    p.mkdir()
    (p / "alive_state.json").write_text(
        __import__("json").dumps(state), encoding="utf-8"
    )
    n = ip.bootstrap_ledger_from_alive_state(tmp_path)
    assert n == 2
    cooled = ip.cooled_keys(tmp_path, cooldown_days=7)
    assert "wshobson/agents" in cooled
    # second bootstrap no-ops
    assert ip.bootstrap_ledger_from_alive_state(tmp_path) == 0


def test_novel_shares_github_cooldown():
    novels = [
        {
            "id": "novel:arxiv:x+wshobson/agents",
            "source": "cross_pattern",
            "github_id": "wshobson/agents",
            "score": 9,
        },
        {
            "id": "novel:arxiv:y+other/repo",
            "source": "cross_pattern",
            "github_id": "other/repo",
            "score": 8,
        },
    ]
    ordered = ip.order_with_cooldown(novels, {"wshobson/agents"})
    assert ordered[0]["github_id"] == "other/repo"
    assert ordered[1]["github_id"] == "wshobson/agents"
