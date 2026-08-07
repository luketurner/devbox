"""Start a detached herdr session running claude on the VM (idempotent)."""
from __future__ import annotations

SESSION = "devbox"


def session_exists_cmd(name: str) -> str:
    # Exits 0 if a session called `name` is already listed.
    return f"herdr list 2>/dev/null | grep -qw {name}"


def build_start_session_cmd(repo: str) -> str:
    claude = "claude rc --permission-mode=bypassPermissions --spawn=same-dir"
    start = f"herdr new -d -s {SESSION} -c ~/{repo} -- {claude}"
    # No-op if the session already exists.
    return f"{session_exists_cmd(SESSION)} || {start}"
