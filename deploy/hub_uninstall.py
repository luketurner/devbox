"""Remove the self-hosted Paseo Hub and everything it brought with it.

Destructive by design: the Postgres volume goes too, so the organization, the
owner login and any API keys are gone. `devbox.py hub uninstall` runs this.

Ordered so each step still has the files the next one deletes, and every step
is guarded or `|| true` -- run_pyinfra retries a failed run from the top, and a
second `hub uninstall` on a clean box has to be a no-op.
"""
from pyinfra.operations import files, server

HOME = "/home/exedev"
CLONE = f"{HOME}/.local/share/paseo-hub"
CONF = f"{HOME}/.config/paseo-hub"

# The unit's ExecStop is `paseo-hub down`, so `disable --now` normally stops the
# stack for us. Don't rely on it: systemd skips ExecStop for a unit that already
# failed, which is the state a crash-looping Hub leaves behind.
server.shell(
    name="Stop and disable paseo hub",
    commands=[
        "export XDG_RUNTIME_DIR=/run/user/$(id -u) && "
        "systemctl --user disable --now paseo-hub.service 2>/dev/null || true"
    ],
)
# --rmi all is the whole point: a plain `down` leaves ~1.5 GiB of images behind,
# which is the memory and disk this command exists to reclaim. Compose only
# removes images its own services reference, and skips any still used by another
# container, so naming postgres/caddy this way is safer than `docker image prune`.
#
# PASEO_HUB_* are passed inline purely so the override file interpolates. A
# teardown never uses the values, and setting them here means this doesn't
# depend on $CLONE/.env surviving or on tailscale being up to regenerate it.
server.shell(
    name="Tear down hub containers, volumes and images",
    commands=[
        f'CF=""; '
        f'[ -f {CLONE}/compose.yml ] && CF="-f {CLONE}/compose.yml"; '
        f'[ -n "$CF" ] && [ -f {CONF}/compose.override.yml ] && '
        f'CF="$CF -f {CONF}/compose.override.yml"; '
        f'if [ -n "$CF" ]; then '
        f'PASEO_HUB_BIND=127.0.0.1 PASEO_HUB_CONF={CONF} '
        f'PASEO_HUB_TAILNET_URL=http://localhost:3000 '
        f'docker compose $CF down --rmi all --volumes --remove-orphans || true; '
        f'fi'
    ],
)
# Catches containers and volumes orphaned by an interrupted run that got as far
# as deleting the clone below. Images need the compose files to identify, so
# they aren't recoverable here -- this is only a safety net, not the main path.
server.shell(
    name="Sweep any orphaned hub containers",
    commands=[
        "docker compose -p paseo-hub down --volumes --remove-orphans "
        "2>/dev/null || true"
    ],
)

files.file(
    name="Remove paseo-hub systemd unit",
    path=f"{HOME}/.config/systemd/user/paseo-hub.service",
    present=False,
)
files.file(
    name="Remove paseo-hub wrapper",
    path=f"{HOME}/.local/bin/paseo-hub",
    present=False,
)
# Takes auth-secret with it, so a later `hub install` bootstraps cleanly rather
# than deriving credentials for rows that no longer exist.
files.directory(
    name="Remove hub config",
    path=CONF,
    present=False,
)
files.directory(
    name="Remove hub clone",
    path=CLONE,
    present=False,
)
server.shell(
    name="Reload user units",
    commands=[
        "export XDG_RUNTIME_DIR=/run/user/$(id -u) && "
        "systemctl --user daemon-reload"
    ],
)
