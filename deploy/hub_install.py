"""Install the self-hosted Paseo Hub: docker compose, tailnet UI, webhook filter.

Split out of deploy.py so a devbox can skip it -- Hub, Postgres and the Caddy
filter cost ~1.5 GiB of images plus a running Postgres, which is memory an
agent microVM could be using instead. `devbox.py hub install` runs this.
"""
import os

from pyinfra import host
from pyinfra.operations import files, git, server

data = host.data
HOME = "/home/exedev"
# files.put resolves relative srcs against the CWD, not this file -- be explicit.
FILES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "files")

# The inventory reads every DEVBOX_* var optionally, because provision and the
# two hub deploys each pass a different subset. That trades a loud KeyError for
# a deploy that would otherwise bootstrap Hub with an empty owner login, so
# assert what this one actually needs.
for _field in ("hub_owner_email", "hub_owner_password"):
    if not getattr(data, _field, None):
        raise ValueError(
            f"hub install needs {_field}: set DEVBOX_{_field.upper()} "
            "(devbox.py hub install does this for you)"
        )

# --- paseo hub (docker compose, tailnet UI + filtered public webhook) -------
# Docker and Compose ship with exeuntu and exedev is in the docker group, so
# no apt work and no sudo here. Lingering is enabled by the provision deploy.
git.repo(
    name="Clone paseo hub",
    src="https://github.com/getpaseo/hub.git",
    dest=f"{HOME}/.local/share/paseo-hub",
)
# files.template is the one op that both interpolates host data and sets mode;
# the owner password must not land in the mode-less ~/.config/devbox.env.
files.template(
    name="Write Hub bootstrap env",
    src=f"{FILES}/hub.env.j2",
    dest=f"{HOME}/.config/paseo-hub/hub.env",
    mode="600",
    owner_email=data.hub_owner_email,
    owner_password=data.hub_owner_password,
)
for _src, _dest, _mode in [
    ("paseo-hub-compose.override.yml", ".config/paseo-hub/compose.override.yml", "644"),
    ("paseo-hub-Caddyfile", ".config/paseo-hub/Caddyfile", "644"),
    ("paseo-hub", ".local/bin/paseo-hub", "755"),
    ("paseo-hub.service", ".config/systemd/user/paseo-hub.service", "644"),
]:
    files.put(
        name=f"Install {_src}",
        src=f"{FILES}/{_src}",
        dest=f"{HOME}/{_dest}",
        mode=_mode,
    )
# No separate "did it stay up?" check, unlike the daemon in deploy.py: the unit
# is Type=oneshot around `docker compose up -d --wait`, so `enable --now` only
# returns success once every container is healthy.
server.shell(
    name="Enable and start paseo hub",
    commands=[
        "export XDG_RUNTIME_DIR=/run/user/$(id -u) && "
        "systemctl --user daemon-reload && "
        "systemctl --user enable --now paseo-hub.service"
    ],
)
