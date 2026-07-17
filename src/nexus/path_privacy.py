"""Path strings safe for committed docs / public artifacts.

Never embed absolute home directories (e.g. /home/<user>/...) in files
that may be pushed to a public GitHub repo.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Optional, Union

PathLike = Union[str, Path]

# Absolute home-style prefixes we never want in public docs
_HOME_ABS = re.compile(
    r"(?:/home/|/Users/|C:\\Users\\|C:/Users/)[^\s`\"'<>|\]]+",
    re.IGNORECASE,
)


def public_path(path: PathLike, root: Optional[PathLike] = None) -> str:
    """Return a path string safe for committed markdown/CSV/JSON.

    Preference order:
    1. Repo-relative to *root* (posix, no leading ./)
    2. ``~/...`` when under the process home directory
    3. Original string with home-style prefixes redacted to ``/path/to/...``
    """
    if path is None:
        return ""
    raw = str(path).strip()
    if not raw or raw in (".", "None", "null"):
        return raw if raw in (".",) else ""

    p = Path(raw).expanduser()
    try:
        p_res = p.resolve()
    except (OSError, RuntimeError):
        p_res = p

    if root is not None:
        try:
            r = Path(root).expanduser().resolve()
            rel = p_res.relative_to(r)
            return rel.as_posix() or "."
        except (ValueError, OSError, RuntimeError):
            pass

    try:
        home = Path.home().resolve()
        rel_h = p_res.relative_to(home)
        return ("~/" + rel_h.as_posix()).replace("~//", "~/")
    except (ValueError, OSError, RuntimeError):
        pass

    return redact_home_paths(str(p_res if p_res else raw))


def redact_home_paths(text: str) -> str:
    """Replace absolute home directory prefixes inside free-form text."""
    if not text or "/home/" not in text and "/Users/" not in text and "Users\\" not in text:
        # Fast path: still check home resolve for this machine
        try:
            home = str(Path.home().resolve())
            if home and home in text:
                text = text.replace(home + os.sep, "~/").replace(home, "~")
        except (OSError, RuntimeError):
            pass
        return text

    def _sub(m: re.Match[str]) -> str:
        s = m.group(0)
        # Keep trailing relative-ish structure after username segment
        # /home/user/foo/bar → /path/to/foo/bar (drop username)
        parts = re.split(r"[/\\]", s)
        # ['', 'home', 'user', 'foo', ...] or ['C:', 'Users', 'user', ...]
        if len(parts) >= 4 and parts[1].lower() in ("home", "users"):
            rest = "/".join(parts[3:])
            return f"/path/to/{rest}" if rest else "/path/to/home"
        if len(parts) >= 4 and parts[0].upper().startswith("C:"):
            rest = "/".join(parts[3:])
            return f"/path/to/{rest}" if rest else "/path/to/home"
        return "/path/to/..."

    try:
        home = str(Path.home().resolve())
        if home and home in text:
            text = text.replace(home + os.sep, "~/").replace(home, "~")
    except (OSError, RuntimeError):
        pass

    return _HOME_ABS.sub(_sub, text)


def scrub_obj(obj: Any, root: Optional[PathLike] = None) -> Any:
    """Recursively scrub strings in dict/list structures (evidence JSON, etc.)."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in ("path", "notes_path", "local_path", "workdir", "project_root", "notes") and isinstance(
                v, str
            ):
                out[k] = public_path(v, root) if v else v
            else:
                out[k] = scrub_obj(v, root)
        return out
    if isinstance(obj, list):
        return [scrub_obj(x, root) for x in obj]
    if isinstance(obj, str):
        return redact_home_paths(obj)
    return obj
