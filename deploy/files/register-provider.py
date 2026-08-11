#!/usr/bin/env python3
"""Register the sandboxed `claude-vm` provider in ~/.paseo/config.json.

The daemon owns this file and rewrites it, so this is a read-modify-write of
one key rather than a template: every other setting is left untouched. Prints
"changed" only when it actually edited something, so the caller can avoid
restarting the daemon (and killing live sessions) on a no-op re-deploy.
"""
import json
import os
import tempfile

CONFIG = os.path.expanduser("~/.paseo/config.json")
WRAPPER = os.path.expanduser("~/.local/bin/paseo-agent-vm")

# `command` is the binary plus a prefix of argv; Paseo appends the adapter's
# own per-session arguments after it.
ENTRY = {
    "extends": "claude",
    "label": "Claude (microVM)",
    "description": "Runs in an ephemeral smolvm microVM with only the workspace mounted",
    "command": [WRAPPER],
}


def main() -> None:
    try:
        with open(CONFIG) as fh:
            config = json.load(fh)
    except FileNotFoundError:
        config = {}

    providers = config.setdefault("agents", {}).setdefault("providers", {})
    if providers.get("claude-vm") == ENTRY:
        print("unchanged")
        return
    providers["claude-vm"] = ENTRY

    os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
    # Atomic replace so a daemon reading concurrently never sees a partial file.
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(CONFIG))
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(config, fh, indent=2)
            fh.write("\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, CONFIG)
    except BaseException:
        os.unlink(tmp)
        raise
    print("changed")


if __name__ == "__main__":
    main()
