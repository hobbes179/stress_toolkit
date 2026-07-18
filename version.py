"""
version.py

Single place for the tool version + the running git commit, surfaced in the
page footer for report traceability (design handoff §7.3: "reports must
identify the tool version"). Screenshots pasted into a stress report therefore
carry an unambiguous "which build produced this" stamp.
"""
from __future__ import annotations

import pathlib
import subprocess
from functools import lru_cache

__version__ = "2.2.1"

_ROOT = pathlib.Path(__file__).resolve().parent


@lru_cache(maxsize=1)
def git_short_sha() -> str:
    """Short SHA of the running checkout. Tries `git`, falls back to reading
    `.git/HEAD` directly (Streamlit Cloud checks the repo out), then 'unknown'.
    Cached — the commit can't change mid-session."""
    try:
        out = subprocess.run(
            ["git", "-C", str(_ROOT), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=2,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except Exception:
        pass
    try:
        head = (_ROOT / ".git" / "HEAD").read_text().strip()
        if head.startswith("ref:"):
            ref = head.split(" ", 1)[1].strip()
            return (_ROOT / ".git" / ref).read_text().strip()[:7]
        return head[:7]
    except Exception:
        return "unknown"


def version_string() -> str:
    """e.g. 'v2.0.0 · a1b2c3d' — for the page footer."""
    return f"v{__version__} · {git_short_sha()}"
