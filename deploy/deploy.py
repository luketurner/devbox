"""Provision an exe.dev devbox: tools, tailscale, repo, claude."""
import os

from pyinfra import host
from pyinfra.operations import apt, files, git, server

data = host.data
HOME = "/home/exedev"
BASHRC = f"{HOME}/.bashrc"
# files.put resolves relative srcs against the CWD, not this file — be explicit.
FILES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "files")

# --- OS packages -------------------------------------------------------------
apt.packages(
    name="Install base tools",
    packages=["mosh", "nnn", "fzf", "fd-find", "extrepo"],
    update=True,
    _sudo=True,
)

# --- mise via extrepo --------------------------------------------------------
server.shell(
    name="Enable mise apt repo via extrepo",
    commands=["extrepo enable mise"],
    _sudo=True,
)
apt.packages(
    name="Install mise",
    packages=["mise"],
    update=True,
    _sudo=True,
)

# --- node via mise -----------------------------------------------------------
# mise itself is on the default PATH (apt puts it in /usr/bin), but anything it
# provides is not: `mise activate` only runs from .bashrc, which pyinfra's
# non-interactive shell never sources. Hence `mise exec` / shims below.
server.shell(
    name="Install node via mise",
    commands=["mise use -g node@lts"],
    _env={"MISE_YES": "1"},
)

# --- paseo CLI via npm (guarded by presence) ---------------------------------
# `mise reshim` is what creates the shim the systemd unit's PATH relies on.
server.shell(
    name="Install paseo CLI",
    commands=[
        f"test -x {HOME}/.local/share/mise/shims/paseo || "
        "(mise exec node@lts -- npm install -g @getpaseo/cli && mise reshim)"
    ],
)

# --- shell config (idempotent, unlike >> appends) ----------------------------
for line in [
    "export EDITOR=vim",
    'eval "$(mise activate bash)"',
    "export GH_HOST=github.int.exe.xyz",
    "export NNN_PLUG='o:fzopen'",
]:
    files.line(
        name=f"bashrc: {line}",
        path=BASHRC,
        line=line.replace("(", r"\(").replace(")", r"\)").replace("$", r"\$"),
        replace=line,
    )

# --- lazygit (guarded by presence) ------------------------------------------
server.shell(
    name="Install lazygit",
    commands=[
        "command -v lazygit >/dev/null 2>&1 || ("
        'LG_VER=$(curl -s "https://api.github.com/repos/jesseduffield/lazygit/releases/latest" '
        "| grep -Po '\"tag_name\": *\"v\\K[^\"]*') && "
        "LG_ARCH=$(uname -m | sed -e 's/aarch64/arm64/') && "
        'curl -Lo /tmp/lazygit.tar.gz "https://github.com/jesseduffield/lazygit/releases/download/v${LG_VER}/lazygit_${LG_VER}_Linux_${LG_ARCH}.tar.gz" && '
        "tar -C /tmp -xf /tmp/lazygit.tar.gz lazygit && "
        "sudo install /tmp/lazygit -D -t /usr/local/bin/)"
    ],
)

# --- herdr (guarded by presence) --------------------------------------------
server.shell(
    name="Install herdr",
    commands=["command -v herdr >/dev/null 2>&1 || curl -fsSL https://herdr.dev/install.sh | sh"],
)

# --- nnn plugins -------------------------------------------------------------
server.shell(
    name="Install nnn plugins",
    commands=[
        f"test -d {HOME}/.config/nnn/plugins || "
        'sh -c "$(curl -Ls https://raw.githubusercontent.com/jarun/nnn/master/plugins/getplugs)"'
    ],
)

# --- Tailscale (guarded by status) ------------------------------------------
server.shell(
    name="Ensure tailscaled running",
    commands=["systemctl start tailscaled"],
    _sudo=True,
)
server.shell(
    name="tailscale up with ephemeral key",
    commands=[
        "tailscale status >/dev/null 2>&1 || "
        f"sudo tailscale up --auth-key='{data.ts_authkey}' --ssh",
        "sudo tailscale set --ssh",
    ],
)

# --- paseo daemon (systemd --user, tailnet-bound) ---------------------------
# Must follow tailscale: the wrapper resolves the tailnet IP at start, and the
# service is started as part of this deploy.
files.put(
    name="Install paseo daemon wrapper",
    src=f"{FILES}/paseo-daemon",
    dest=f"{HOME}/.local/bin/paseo-daemon",
    mode="755",
)
files.put(
    name="Install paseo systemd user unit",
    src=f"{FILES}/paseo.service",
    dest=f"{HOME}/.config/systemd/user/paseo.service",
    mode="644",
)
server.shell(
    name="Enable lingering for user services",
    commands=["loginctl enable-linger exedev"],
    _sudo=True,
)
server.shell(
    name="Enable and start paseo daemon",
    commands=[
        # XDG_RUNTIME_DIR is unset over non-interactive SSH; systemctl --user
        # can't find the user manager without it.
        "export XDG_RUNTIME_DIR=/run/user/$(id -u) && "
        "systemctl --user daemon-reload && "
        "systemctl --user enable --now paseo.service"
    ],
)

# --- paseo hub (docker compose, tailnet UI + filtered public webhook) -------
# Docker and Compose ship with exeuntu and exedev is in the docker group, so
# no apt work and no sudo here. Lingering is already enabled above.
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
server.shell(
    name="Enable and start paseo hub",
    commands=[
        "export XDG_RUNTIME_DIR=/run/user/$(id -u) && "
        "systemctl --user daemon-reload && "
        "systemctl --user enable --now paseo-hub.service"
    ],
)

# --- GitHub repo clone (idempotent) -----------------------------------------
# The reflection endpoint names the attached github integration = repo dir.
git.repo(
    name="Clone the target repo",
    src=f"https://github.int.exe.xyz/{data.repo}.git",
    dest=f"{HOME}/{data.repo}",
    _env={"GH_HOST": "github.int.exe.xyz"},
)

# --- Claude token persisted (secret on VM, by design) -----------------------
files.line(
    name="Persist CLAUDE_CODE_OAUTH_TOKEN",
    path=f"{HOME}/.config/devbox.env",
    line=f"export CLAUDE_CODE_OAUTH_TOKEN={data.claude_token}",
    replace=f"export CLAUDE_CODE_OAUTH_TOKEN={data.claude_token}",
)
files.line(
    name="Source devbox.env from bashrc",
    path=BASHRC,
    line=r"source ~/.config/devbox.env",
)

# --- Claude plugins (guarded / tolerant of already-installed) ---------------
_plugins = [
    "superpowers@superpowers-marketplace",
    "elements-of-style@superpowers-marketplace",
    "double-shot-latte@superpowers-marketplace",
    "superpowers-chrome@superpowers-marketplace",
    "frontend-design@claude-plugins-official",
]
server.shell(
    name="Add claude marketplace",
    commands=["claude plugin marketplace add obra/superpowers-marketplace || true"],
)
for plugin in _plugins:
    server.shell(
        name=f"Install claude plugin {plugin}",
        commands=[f"claude plugin install {plugin} || true"],
    )
