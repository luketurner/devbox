"""Config loading, merging, and validation for devbox."""
from __future__ import annotations

import tomllib
from pathlib import Path

ACCOUNT_PATH = Path.home() / ".config" / "devbox" / "config.toml"


def load_toml(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open("rb") as fh:
        return tomllib.load(fh)


def _encode(data: dict) -> str:
    # Minimal TOML writer: all values here are strings/bools. Keeps us off a
    # third-party TOML *writer* dependency (stdlib only reads TOML).
    lines = []
    for key, value in data.items():
        if isinstance(value, bool):
            lines.append(f"{key} = {str(value).lower()}")
        else:
            escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'{key} = "{escaped}"')
    return "\n".join(lines) + "\n"


def save_toml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    path.write_text(_encode(data))
    path.chmod(0o600)


def merge(*layers: dict) -> dict:
    result: dict = {}
    for layer in layers:
        for key, value in layer.items():
            if value in (None, ""):
                continue
            result[key] = value
    return result


def missing_fields(data: dict, required: list[str]) -> list[str]:
    return [f for f in required if not data.get(f)]
