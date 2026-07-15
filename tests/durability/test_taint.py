"""Unit tests for taint labels (no network)."""

from __future__ import annotations

import pytest

from nexus.durability import TaintError, TaintLevel, TaintSet
from nexus.durability.taint import TAINT_REGISTRY_KEY, infer_source_level


def test_mined_not_readable_as_trusted_without_promote():
    ts = TaintSet()
    ts.stamp_mined("digest", source="scout_repos/wmcmahan__cycgraph")
    assert ts.level_of("digest") is TaintLevel.MINED
    assert ts.is_tainted("digest")
    assert not ts.is_trusted("digest")
    with pytest.raises(TaintError) as ei:
        ts.require_trusted("digest")
    assert ei.value.key == "digest"
    assert ei.value.level is TaintLevel.MINED

    # explicit promote gate required
    with pytest.raises(TaintError):
        ts.promote("digest", gate="")

    ts.promote("digest", gate="human-review:grade>=10")
    assert ts.is_trusted("digest")
    ts.require_trusted("digest")  # no raise
    info = ts.info("digest")
    assert info is not None
    assert info.promoted_from == "mined"
    assert info.gate == "human-review:grade>=10"


def test_mcp_and_user_levels():
    ts = TaintSet()
    ts.stamp_mcp("tool_out", source="mcp:filesystem")
    ts.stamp("prefs", TaintLevel.USER, source="user")
    assert ts.level_of("tool_out") is TaintLevel.EXTERNAL_MCP
    assert ts.level_of("prefs") is TaintLevel.USER
    with pytest.raises(TaintError):
        ts.require_trusted("tool_out")


def test_propagate_derived_from_tainted_inputs():
    ts = TaintSet()
    ts.stamp_mined("a")
    ts.stamp("b", TaintLevel.TRUSTED)
    new = ts.propagate(["a", "b"], ["summary", "plan"], agent_id="worker")
    assert "summary" in new
    assert ts.level_of("summary") is TaintLevel.DERIVED
    assert ts.level_of("plan") is TaintLevel.DERIVED
    # clean inputs → no propagation
    ts2 = TaintSet()
    ts2.stamp("x", TaintLevel.TRUSTED)
    assert ts2.propagate(["x"], ["y"]) == {}


def test_embed_extract_roundtrip():
    ts = TaintSet()
    ts.stamp_mined("blob", source="mine_eval/foo")
    state: dict = {"blob": {"n": 1}}
    ts.embed(state)
    assert TAINT_REGISTRY_KEY in state
    ts2 = TaintSet.extract(state)
    assert ts2.level_of("blob") is TaintLevel.MINED
    with pytest.raises(TaintError):
        ts2.require_trusted("blob")


def test_infer_source_level():
    assert infer_source_level("scout_repos/phodal__routa") is TaintLevel.MINED
    assert infer_source_level("/home/x/.nexus_workspaces/mine_eval/r") is TaintLevel.MINED
    assert infer_source_level("mcp:tools/list") is TaintLevel.EXTERNAL_MCP
    assert infer_source_level("user:stdin") is TaintLevel.USER
    assert infer_source_level("") is TaintLevel.TRUSTED


def test_cannot_stamp_registry_key():
    ts = TaintSet()
    with pytest.raises(TaintError):
        ts.stamp(TAINT_REGISTRY_KEY, TaintLevel.MINED)


def test_unknown_level_degrades_not_trusted():
    assert TaintLevel.parse("totally-unknown") is TaintLevel.DERIVED
    assert TaintLevel.parse(TaintLevel.MINED) is TaintLevel.MINED


def test_serde():
    ts = TaintSet(default_level=TaintLevel.TRUSTED)
    ts.stamp_mined("k", source="github:org/repo")
    d = ts.to_dict()
    ts2 = TaintSet.from_dict(d)
    assert ts2.level_of("k") is TaintLevel.MINED
    assert ts2.info("k").source == "github:org/repo"
