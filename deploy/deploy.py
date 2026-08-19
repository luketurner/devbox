"""Provision an exe.dev devbox: tools, tailscale, repo, claude."""
import os

from pyinfra import host
from pyinfra.operations import apt, files, server

data = host.data
HOME = "/home/exedev"
BASHRC = f"{HOME}/.bashrc"
# files.put resolves relative srcs against the CWD, not this file — be explicit.
FILES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "files")

# The inventory reads every DEVBOX_* var optionally, because provision and the
# two hub deploys each pass a different subset. Without that KeyError to lean
# on, an unset key would quietly deploy `tailscale up --auth-key=None`.
for _field in ("ts_authkey", "claude_token",
               "agent_pool_size", "agent_memory"):
    if not getattr(data, _field, None):
        raise ValueError(
            f"provision needs {_field}: set the matching DEVBOX_* env var "
            "(devbox.py provision does this for you)"
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
# Type=simple means `enable --now` returns success the moment systemd forks, so
# an ExecStart that dies immediately -- a bad interpreter, a missing binary --
# is reported as a successful deploy and only shows up later as a daemon that
# isn't listening. Check it actually stayed up, and print why if it didn't.
server.shell(
    name="Verify paseo daemon is running",
    commands=[
        "export XDG_RUNTIME_DIR=/run/user/$(id -u) && sleep 5 && "
        "systemctl --user is-active --quiet paseo.service || { "
        "systemctl --user status paseo.service --no-pager -l | tail -n 20; "
        "exit 1; }"
    ],
)

# --- exe.dev GitHub integration reachable from microVMs ---------------------
# The integration is served on a link-local address a guest cannot route to,
# but smolvm's TSI backend makes the devbox's loopback reachable from inside
# one. socat ships with the image, so no extra package. 443 is privileged,
# hence a system unit rather than a --user one.
files.put(
    name="Install github proxy unit",
    src=f"{FILES}/paseo-github-proxy.service",
    dest="/etc/systemd/system/paseo-github-proxy.service",
    mode="644",
    _sudo=True,
)
server.shell(
    name="Enable and start github proxy",
    commands=[
        "systemctl daemon-reload && "
        "systemctl enable --now paseo-github-proxy.service && "
        # Same Type=simple caveat as the daemon above: verify it stayed up.
        "sleep 3 && { systemctl is-active --quiet paseo-github-proxy.service || { "
        "systemctl status paseo-github-proxy.service --no-pager -l | tail -n 20; "
        "exit 1; }; }"
    ],
    _sudo=True,
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
# Supplementary groups are fixed when a process starts, so the systemd user
# manager -- and the paseo daemon and microVMs it spawns -- keep whatever
# groups they had at boot. The usermod above therefore does nothing for them
# until the manager restarts, which is why a claude-vm session fails with
# "Cannot access /dev/kvm" long after the deploy reported success.
#
# Checking /etc/group is not enough: it lists kvm the moment usermod runs,
# while the running manager is still stale. Compare against the manager's
# actual group set, so a re-provision doesn't needlessly bounce live agents.
server.shell(
    name="Restart user manager if it predates the kvm group",
    commands=[
        'KVM_GID="$(getent group kvm | cut -d: -f3)"; '
        'UID_N="$(id -u exedev)"; '
        'MPID="$(systemctl show "user@${UID_N}.service" -p MainPID --value)"; '
        'if [ -z "$MPID" ] || [ "$MPID" = "0" ] || '
        '! grep "^Groups:" "/proc/$MPID/status" | tr " " "\\n" '
        '| grep -qx "$KVM_GID"; then '
        'systemctl restart "user@${UID_N}.service"; sleep 5; fi'
    ],
    _sudo=True,
)
files.put(
    name="Install agent image Dockerfile",
    src=f"{FILES}/paseo-agent.Dockerfile",
    dest=f"{HOME}/.config/paseo-agent/Dockerfile",
    mode="644",
)
# COPYed into the image, so it has to live in the build context.
files.put(
    name="Install agent image entrypoint",
    src=f"{FILES}/agent-entry",
    dest=f"{HOME}/.config/paseo-agent/agent-entry",
    mode="755",
)
# Shared by the pool build and paseo-agent-vm's rebuild path, so both apply the
# same egress allowlist. Installed before the build below, which reads it.
files.put(
    name="Install agent pool memory check",
    src=f"{FILES}/paseo-agent-memcheck",
    dest=f"{HOME}/.local/bin/paseo-agent-memcheck",
    mode="755",
)
# Deliberately ahead of the template below: the whole point is that a pool the
# box cannot hold never reaches pool.env. Writing it first and failing after
# would leave paseo-agent-vm reading a POOL_SIZE whose machines were never
# built, and recycle() would create them on demand -- the OOM this prevents.
server.shell(
    name="Check the agent pool fits in memory",
    commands=[
        f"{HOME}/.local/bin/paseo-agent-memcheck "
        f"{data.agent_pool_size} {data.agent_memory}"
    ],
)
# Read by both paseo-agent-build and paseo-agent-vm, so the pool geometry has a
# single source. Installed before the build below, which sources it and hashes
# it -- changing the size or the memory therefore forces a restock rather than
# printing "unchanged" over a pool with the old geometry.
files.template(
    name="Install agent pool config",
    src=f"{FILES}/paseo-agent-pool.env.j2",
    dest=f"{HOME}/.config/paseo-agent/pool.env",
    mode="644",
    agent_pool_size=data.agent_pool_size,
    agent_memory=data.agent_memory,
)
files.put(
    name="Install agent egress allowlist generator",
    src=f"{FILES}/paseo-agent-egress",
    dest=f"{HOME}/.local/bin/paseo-agent-egress",
    mode="755",
)
files.put(
    name="Install agent image build script",
    src=f"{FILES}/paseo-agent-build",
    dest=f"{HOME}/.local/bin/paseo-agent-build",
    mode="755",
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
# image has to reach smolvm as a `docker save` archive. The script guards on a
# hash of the Dockerfile, so editing it actually triggers a rebuild.
server.shell(
    name="Build agent microVM image",
    commands=[f"{HOME}/.local/bin/paseo-agent-build"],
)
# Dev servers inside the microVM are forwarded to the devbox's 127.0.0.1 only
# (smolvm rejects a bind IP), so republish them onto the tailnet. --http avoids
# depending on tailnet HTTPS certs, matching how the daemon is served.
for _port in ["5173", "8000", "8081"]:
    server.shell(
        name=f"tailscale serve dev port {_port}",
        commands=[f"tailscale serve --bg --http {_port} {_port}"],
        _sudo=True,
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
