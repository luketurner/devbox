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
    packages=["fd-find"],
    update=True,
    _sudo=True,
)

# --- node via NodeSource -----------------------------------------------------
# Ubuntu's own nodejs is 18.x (EOL). Guarded on the sources file so a re-deploy
# doesn't re-run the setup script.
server.shell(
    name="Enable nodesource apt repo",
    commands=[
        "test -f /etc/apt/sources.list.d/nodesource.list || "
        "curl -fsSL https://deb.nodesource.com/setup_lts.x | bash -"
    ],
    _sudo=True,
)
apt.packages(
    name="Install node",
    packages=["nodejs"],
    update=True,
    _sudo=True,
)

# --- paseo CLI via npm (guarded by presence) ---------------------------------
# Installs to /usr/lib/node_modules with the binary in /usr/bin, which is
# already on the default non-interactive PATH.
server.shell(
    name="Install paseo CLI",
    commands=["command -v paseo >/dev/null 2>&1 || npm install -g @getpaseo/cli"],
    _sudo=True,
)

# --- shell config (idempotent, unlike >> appends) ----------------------------
for line in [
    "export EDITOR=vim",
    "export GH_HOST=github.int.exe.xyz",
]:
    files.line(
        name=f"bashrc: {line}",
        path=BASHRC,
        line=line.replace("(", r"\(").replace(")", r"\)").replace("$", r"\$"),
        replace=line,
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

# --- smolvm + sandboxed agent provider --------------------------------------
# --no-modify-path: the installer would append its own PATH line to .bashrc,
# which fights the files.line-managed block above. The wrapper uses an absolute
# path, so this is only for interactive use.
server.shell(
    name="Install smolvm",
    commands=[
        f"test -x {HOME}/.smolvm/smolvm || "
        "curl -sSL https://smolmachines.com/install.sh | bash -s -- --no-modify-path"
    ],
)
files.line(
    name="bashrc: smolvm on PATH",
    path=BASHRC,
    line=r"export PATH=\$HOME/.smolvm:\$PATH",
    replace="export PATH=$HOME/.smolvm:$PATH",
)
# smolvm needs /dev/kvm, which is root:kvm 0660.
server.shell(
    name="Grant exedev access to /dev/kvm",
    commands=["usermod -aG kvm exedev"],
    _sudo=True,
)
files.put(
    name="Install agent image Dockerfile",
    src=f"{FILES}/paseo-agent.Dockerfile",
    dest=f"{HOME}/.config/paseo-agent/Dockerfile",
    mode="644",
)
files.put(
    name="Install paseo-agent-vm wrapper",
    src=f"{FILES}/paseo-agent-vm",
    dest=f"{HOME}/.local/bin/paseo-agent-vm",
    mode="755",
)
files.put(
    name="Install provider registration script",
    src=f"{FILES}/register-provider.py",
    dest=f"{HOME}/.config/paseo-agent/register-provider.py",
    mode="755",
)
# A bare --image name is always a registry reference, so the locally built
# image has to reach smolvm as a `docker save` archive.
server.shell(
    name="Build agent microVM image",
    commands=[
        f"test -f {HOME}/.local/share/paseo-agent.tar || ("
        f"docker build -t paseo-agent:latest {HOME}/.config/paseo-agent && "
        f"docker save paseo-agent:latest -o {HOME}/.local/share/paseo-agent.tar)"
    ],
)
# Restart only on a real config change, so re-deploys don't kill live sessions.
server.shell(
    name="Register claude-vm provider",
    commands=[
        "export XDG_RUNTIME_DIR=/run/user/$(id -u) && "
        f"if python3 {HOME}/.config/paseo-agent/register-provider.py | grep -q changed; "
        "then systemctl --user restart paseo.service; fi"
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
