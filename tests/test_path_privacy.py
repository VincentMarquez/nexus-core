"""path_privacy: never leak absolute home paths into public artifacts."""

from pathlib import Path

from nexus.path_privacy import public_path, redact_home_paths, scrub_obj


def test_public_path_relative_to_root(tmp_path: Path):
    root = tmp_path / "nexus-core"
    root.mkdir()
    p = root / ".nexus_state" / "foo.md"
    p.parent.mkdir()
    p.write_text("x")
    assert public_path(p, root) == ".nexus_state/foo.md"


def test_public_path_home_tilde(tmp_path: Path, monkeypatch):
    home = tmp_path / "homeuser"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    target = home / "proj" / "a.txt"
    target.parent.mkdir()
    target.write_text("x")
    # resolve may differ; accept ~/proj/a.txt form
    out = public_path(target)
    assert "homeuser" not in out
    assert out.startswith("~/") or out == "proj/a.txt" or "path/to" in out


def test_redact_home_paths_unix():
    s = "plan=`/home/someone/nexus-core/.nexus_state/x.md`"
    out = redact_home_paths(s)
    assert "/home/someone" not in out
    assert "nexus-core" in out or "path/to" in out


def test_scrub_obj_paths():
    obj = {
        "path": "/home/someone/nexus-core/.nexus_state/t.json",
        "nested": {"notes_path": "/home/someone/nexus-core/docs/a.csv"},
        "text": "see /home/someone/secret",
    }
    out = scrub_obj(obj, root=None)
    assert "/home/someone" not in str(out)
