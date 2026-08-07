"""Provision an exe.dev devbox: tools, tailscale, repo, claude."""
from pyinfra import host
from pyinfra.operations import apt, files, git, server

data = host.data
HOME = "/home/exedev"
BASHRC = f"{HOME}/.bashrc"

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
