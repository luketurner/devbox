# pyinfra Devbox Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the bash devbox scripts with a single idempotent `uv run devbox.py <user/repo>` that creates an exe.dev GitHub integration + VM and provisions it via pyinfra so a detached `claude` session is waiting.

**Architecture:** A local Python orchestrator (`devbox.py` + `devbox/` package) handles config, secrets, exe.dev lifecycle (create-if-missing), Tailscale key minting, and launching pyinfra. All in-VM provisioning lives in a pyinfra deploy (`deploy/`) run over SSH. Secrets are passed to pyinfra via environment variables, never argv. Browser login happens only locally (Claude `setup-token`); Tailscale uses an API-minted ephemeral key — no browser during a run.

**Tech Stack:** Python 3.11+, uv, pyinfra (v3), httpx, questionary, pytest.

## Global Constraints

- Python **3.11+** (uses stdlib `tomllib`).
- Package/dependency management via **uv** (`pyproject.toml`); run everything with `uv run`.
- Secrets (Claude token, Tailscale auth key, Tailscale OAuth secret) must **never** appear in process argv — pass via environment or files only.
- Every provisioning step must be **idempotent**: re-running `devbox.py` against an existing VM converges without error or duplication.
- **No browser interaction and no copy/paste during a run.** Browser login is confined to a one-time local `claude setup-token`.
- Account config/secrets live in `~/.config/devbox/config.toml`; per-repo config in gitignored `.devbox/<repo>.toml`.
- Follow existing repo conventions; the three bash scripts are removed at the end.

---

### Task 1: Project scaffold (uv, package layout, test harness)

**Files:**
- Create: `pyproject.toml`
- Create: `devbox/__init__.py`
- Create: `deploy/__init__.py` (empty; keeps `deploy` importable for tests)
- Create: `tests/__init__.py`
- Create: `tests/test_scaffold.py`
- Create: `.gitignore`

**Interfaces:**
- Consumes: nothing.
- Produces: a working `uv run pytest`; `devbox` importable as a package with `devbox.__version__`.

- [ ] **Step 1: Write the failing test**

`tests/test_scaffold.py`:
```python
import devbox


def test_package_has_version():
    assert isinstance(devbox.__version__, str)
    assert devbox.__version__
```

- [ ] **Step 2: Create `pyproject.toml`**

```toml
[project]
name = "devbox"
version = "0.1.0"
description = "Provision an exe.dev VM for a GitHub repo via pyinfra"
requires-python = ">=3.11"
dependencies = [
    "pyinfra>=3,<4",
    "httpx>=0.27",
    "questionary>=2",
]

[project.scripts]
devbox = "devbox.cli:main"

[dependency-groups]
dev = ["pytest>=8"]

[tool.pytest.ini_options]
testpaths = ["tests"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["devbox"]
```

- [ ] **Step 3: Create the package files**

`devbox/__init__.py`:
```python
__version__ = "0.1.0"
```

`deploy/__init__.py`: empty file.
`tests/__init__.py`: empty file.

`.gitignore`:
```gitignore
# devbox per-repo config/secrets
.devbox/

# python
__pycache__/
*.pyc
.venv/
.pytest_cache/
```

- [ ] **Step 4: Run the test**

Run: `uv run pytest tests/test_scaffold.py -v`
Expected: PASS (uv resolves deps and creates the environment on first run).

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml devbox/ deploy/ tests/ .gitignore
git commit -m "chore: scaffold uv project and package layout"
```

---

### Task 2: Config loading, merging, and validation (`devbox/config.py`)

**Files:**
- Create: `devbox/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `ACCOUNT_PATH: Path` — `~/.config/devbox/config.toml`.
  - `repo_config_path(repo_name: str) -> Path` → `.devbox/<repo_name>.toml`.
  - `load_toml(path: Path) -> dict` (returns `{}` if the file is absent).
  - `save_toml(path: Path, data: dict) -> None` (creates parent dirs; TOML-encodes).
  - `merge(*layers: dict) -> dict` — later layers override earlier; keys whose value is `None` or `""` do not override.
  - `missing_fields(data: dict, required: list[str]) -> list[str]`.

- [ ] **Step 1: Write the failing tests**

`tests/test_config.py`:
```python
from pathlib import Path

from devbox import config


def test_merge_later_layers_win():
    merged = config.merge({"a": 1, "b": 2}, {"b": 3})
    assert merged == {"a": 1, "b": 3}


def test_merge_ignores_empty_overrides():
    merged = config.merge({"a": "keep"}, {"a": None, "b": ""})
    assert merged["a"] == "keep"
    assert "b" not in merged


def test_missing_fields():
    assert config.missing_fields({"a": "x"}, ["a", "b"]) == ["b"]
    assert config.missing_fields({"a": "x", "b": "y"}, ["a", "b"]) == []


def test_toml_round_trip(tmp_path: Path):
    p = tmp_path / "sub" / "c.toml"
    config.save_toml(p, {"github_user": "me", "repo_name": "r"})
    assert config.load_toml(p) == {"github_user": "me", "repo_name": "r"}


def test_load_missing_returns_empty(tmp_path: Path):
    assert config.load_toml(tmp_path / "nope.toml") == {}


def test_repo_config_path():
    assert config.repo_config_path("myrepo") == Path(".devbox") / "myrepo.toml"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL (`ModuleNotFoundError` / attributes undefined).

- [ ] **Step 3: Implement `devbox/config.py`**

```python
"""Config loading, merging, and validation for devbox."""
from __future__ import annotations

import tomllib
from pathlib import Path

ACCOUNT_PATH = Path.home() / ".config" / "devbox" / "config.toml"


def repo_config_path(repo_name: str) -> Path:
    return Path(".devbox") / f"{repo_name}.toml"


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
    path.write_text(_encode(data))


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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add devbox/config.py tests/test_config.py
git commit -m "feat: config load/merge/validate"
```

---

### Task 3: exe.dev CLI wrappers (`devbox/exe.py`)

**Files:**
- Create: `devbox/exe.py`
- Test: `tests/test_exe.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `vm_host(prefix: str, repo: str) -> str` → `"<prefix>-<repo>.exe.xyz"`.
  - `build_integration_add_args(user: str, repo: str) -> list[str]`.
  - `build_new_vm_args(name: str, tags: list[str]) -> list[str]`.
  - `parse_items(raw: str, keys: list[str]) -> list[dict]` — parse `--json` output whether it is a bare list or a dict wrapping the list under one of `keys`.
  - `integration_exists(items: list[dict], name: str) -> bool`.
  - `vm_exists(items: list[dict], name: str) -> bool`.
  - `run_exe(args, *, input=None, capture=True) -> subprocess.CompletedProcess` — runs `ssh exe.dev <args...>`.
  - `list_integrations() -> list[dict]`, `add_integration(user, repo) -> None`,
    `list_vms() -> list[dict]`, `create_vm(name, tags) -> None`.

> **Assumption to verify at implementation time:** the exact JSON shape of
> `integrations list --json` and `ls --json`. `parse_items` is written to
> tolerate either a bare list or a dict with the list under `integrations` /
> `machines` / `vms`, and objects keyed by `name`. Confirm with a live
> `ssh exe.dev ls --json` and adjust the `keys`/name field if needed.

- [ ] **Step 1: Write the failing tests**

`tests/test_exe.py`:
```python
from devbox import exe


def test_vm_host():
    assert exe.vm_host("acme", "widgets") == "acme-widgets.exe.xyz"


def test_build_integration_add_args():
    args = exe.build_integration_add_args("me", "repo")
    assert args == [
        "integrations", "add", "github",
        "--name", "repo",
        "--repository", "me/repo",
        "--attach", "tag:repo",
    ]


def test_build_new_vm_args():
    args = exe.build_new_vm_args("acme-repo", ["dev", "repo"])
    assert args == [
        "new", "--name", "acme-repo",
        "--tag", "dev", "--tag", "repo", "--json",
    ]


def test_parse_items_bare_list():
    assert exe.parse_items('[{"name": "a"}]', ["machines"]) == [{"name": "a"}]


def test_parse_items_wrapped():
    raw = '{"machines": [{"name": "a"}, {"name": "b"}]}'
    assert exe.parse_items(raw, ["machines", "vms"]) == [
        {"name": "a"}, {"name": "b"},
    ]


def test_exists_predicates():
    items = [{"name": "repo"}, {"name": "other"}]
    assert exe.integration_exists(items, "repo") is True
    assert exe.vm_exists(items, "missing") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_exe.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `devbox/exe.py`**

```python
"""Thin wrappers over the `ssh exe.dev ...` CLI."""
from __future__ import annotations

import json
import subprocess


def vm_host(prefix: str, repo: str) -> str:
    return f"{prefix}-{repo}.exe.xyz"


def build_integration_add_args(user: str, repo: str) -> list[str]:
    return [
        "integrations", "add", "github",
        "--name", repo,
        "--repository", f"{user}/{repo}",
        "--attach", f"tag:{repo}",
    ]


def build_new_vm_args(name: str, tags: list[str]) -> list[str]:
    args = ["new", "--name", name]
    for tag in tags:
        args += ["--tag", tag]
    args.append("--json")
    return args


def parse_items(raw: str, keys: list[str]) -> list[dict]:
    data = json.loads(raw)
    if isinstance(data, list):
        return data
    for key in keys:
        if isinstance(data.get(key), list):
            return data[key]
    return []


def _has_name(items: list[dict], name: str) -> bool:
    return any(item.get("name") == name for item in items)


def integration_exists(items: list[dict], name: str) -> bool:
    return _has_name(items, name)


def vm_exists(items: list[dict], name: str) -> bool:
    return _has_name(items, name)


def run_exe(args, *, input=None, capture=True):
    return subprocess.run(
        ["ssh", "exe.dev", *args],
        input=input,
        capture_output=capture,
        text=True,
        check=True,
    )


def list_integrations() -> list[dict]:
    out = run_exe(["integrations", "list", "--json"]).stdout
    return parse_items(out, ["integrations"])


def add_integration(user: str, repo: str) -> None:
    run_exe(build_integration_add_args(user, repo))


def list_vms() -> list[dict]:
    out = run_exe(["ls", "--json"]).stdout
    return parse_items(out, ["machines", "vms"])


def create_vm(name: str, tags: list[str]) -> None:
    run_exe(build_new_vm_args(name, tags))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_exe.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add devbox/exe.py tests/test_exe.py
git commit -m "feat: exe.dev CLI wrappers and idempotency predicates"
```

---

### Task 4: Tailscale key minting (`devbox/tailscale.py`)

**Files:**
- Create: `devbox/tailscale.py`
- Test: `tests/test_tailscale.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `build_key_request(tag: str) -> dict` — request body for an ephemeral,
    pre-authorized, non-reusable, tagged auth key.
  - `parse_key_response(data: dict) -> str` — returns `data["key"]`.
  - `get_access_token(client_id, client_secret, *, client) -> str` — OAuth
    client-credentials exchange; `client` is an injected `httpx.Client`.
  - `mint_key(tailnet, tag, client_id, client_secret, *, client) -> str`.
  - `TS_API = "https://api.tailscale.com"`.

- [ ] **Step 1: Write the failing tests**

`tests/test_tailscale.py`:
```python
import httpx

from devbox import tailscale


def test_build_key_request():
    body = tailscale.build_key_request("tag:devbox")
    caps = body["capabilities"]["devices"]["create"]
    assert caps["ephemeral"] is True
    assert caps["preauthorized"] is True
    assert caps["reusable"] is False
    assert caps["tags"] == ["tag:devbox"]


def test_parse_key_response():
    assert tailscale.parse_key_response({"key": "tskey-abc"}) == "tskey-abc"


def test_mint_key_flow():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v2/oauth/token":
            return httpx.Response(200, json={"access_token": "at-123"})
        assert request.headers["Authorization"] == "Bearer at-123"
        assert request.url.path == "/api/v2/tailnet/example.com/keys"
        return httpx.Response(200, json={"key": "tskey-xyz"})

    client = httpx.Client(transport=httpx.MockTransport(handler),
                          base_url=tailscale.TS_API)
    key = tailscale.mint_key("example.com", "tag:devbox", "cid", "csecret",
                             client=client)
    assert key == "tskey-xyz"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_tailscale.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `devbox/tailscale.py`**

```python
"""Mint ephemeral Tailscale auth keys via OAuth client credentials."""
from __future__ import annotations

import httpx

TS_API = "https://api.tailscale.com"


def build_key_request(tag: str) -> dict:
    return {
        "capabilities": {
            "devices": {
                "create": {
                    "reusable": False,
                    "ephemeral": True,
                    "preauthorized": True,
                    "tags": [tag],
                }
            }
        },
        "expirySeconds": 900,
    }


def parse_key_response(data: dict) -> str:
    return data["key"]


def get_access_token(client_id: str, client_secret: str, *,
                     client: httpx.Client) -> str:
    resp = client.post(
        "/api/v2/oauth/token",
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        },
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def mint_key(tailnet: str, tag: str, client_id: str, client_secret: str, *,
             client: httpx.Client) -> str:
    token = get_access_token(client_id, client_secret, client=client)
    resp = client.post(
        f"/api/v2/tailnet/{tailnet}/keys",
        headers={"Authorization": f"Bearer {token}"},
        json=build_key_request(tag),
    )
    resp.raise_for_status()
    return parse_key_response(resp.json())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tailscale.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add devbox/tailscale.py tests/test_tailscale.py
git commit -m "feat: mint ephemeral Tailscale auth keys via OAuth"
```

---

### Task 5: Claude token caching (`devbox/claude_auth.py`)

**Files:**
- Create: `devbox/claude_auth.py`
- Test: `tests/test_claude_auth.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `extract_token(output: str) -> str` — pull the `sk-ant-oat...` token from
    `claude setup-token` stdout (last whitespace-delimited token starting with
    `sk-ant-`).
  - `ensure_token(cached: str | None, *, runner=_run_setup_token) -> str` — if a
    cached token is present, return it; otherwise call `runner()` (which invokes
    `claude setup-token`) and return the extracted token. `runner` is injected
    for testing.

> **Assumption to verify at implementation time:** the exact stdout format of
> `claude setup-token` and the token prefix. `extract_token` matches
> `sk-ant-`-prefixed tokens; confirm on a real run and adjust the prefix/parse
> if the CLI changed.

- [ ] **Step 1: Write the failing tests**

`tests/test_claude_auth.py`:
```python
from devbox import claude_auth


def test_extract_token():
    out = "Paste this token into CI:\n  sk-ant-oat01-ABCdef123  \nDone.\n"
    assert claude_auth.extract_token(out) == "sk-ant-oat01-ABCdef123"


def test_ensure_token_returns_cached():
    called = False

    def runner():
        nonlocal called
        called = True
        return "unused"

    assert claude_auth.ensure_token("sk-ant-cached", runner=runner) == "sk-ant-cached"
    assert called is False


def test_ensure_token_runs_when_missing():
    assert claude_auth.ensure_token(None, runner=lambda: "sk-ant-new") == "sk-ant-new"
    assert claude_auth.ensure_token("", runner=lambda: "sk-ant-new") == "sk-ant-new"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_claude_auth.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `devbox/claude_auth.py`**

```python
"""Obtain and cache a Claude Code OAuth token (local browser login, once)."""
from __future__ import annotations

import re
import subprocess

_TOKEN_RE = re.compile(r"sk-ant-[A-Za-z0-9\-_]+")


def extract_token(output: str) -> str:
    matches = _TOKEN_RE.findall(output)
    if not matches:
        raise ValueError("no sk-ant- token found in `claude setup-token` output")
    return matches[-1]


def _run_setup_token() -> str:
    # Inherits the terminal so the local browser OAuth loopback works.
    proc = subprocess.run(
        ["claude", "setup-token"],
        capture_output=True,
        text=True,
        check=True,
    )
    return extract_token(proc.stdout)


def ensure_token(cached: str | None, *, runner=_run_setup_token) -> str:
    if cached:
        return cached
    return runner()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_claude_auth.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add devbox/claude_auth.py tests/test_claude_auth.py
git commit -m "feat: cache Claude setup-token from local browser login"
```

---

### Task 6: pyinfra invocation (`devbox/provision.py`)

**Files:**
- Create: `devbox/provision.py`
- Test: `tests/test_provision.py`

**Interfaces:**
- Consumes: `devbox.exe.vm_host` (host string).
- Produces:
  - `INVENTORY = "deploy/inventory.py"`, `DEPLOY = "deploy/deploy.py"`.
  - `build_pyinfra_args() -> list[str]` → `["pyinfra", INVENTORY, DEPLOY]`
    (contains **no secrets**).
  - `build_env(base: dict, *, host, ts_key, claude_token, repo) -> dict` — copies
    `base` and adds `DEVBOX_HOST`, `DEVBOX_TS_AUTHKEY`, `CLAUDE_CODE_OAUTH_TOKEN`,
    `DEVBOX_REPO`.
  - `run_pyinfra(env: dict) -> subprocess.CompletedProcess`.

- [ ] **Step 1: Write the failing tests**

`tests/test_provision.py`:
```python
from devbox import provision


def test_args_carry_no_secrets():
    args = provision.build_pyinfra_args()
    assert args[0] == "pyinfra"
    joined = " ".join(args)
    assert "tskey" not in joined and "sk-ant" not in joined


def test_build_env_sets_secrets_in_env():
    env = provision.build_env(
        {"PATH": "/usr/bin"},
        host="acme-repo.exe.xyz",
        ts_key="tskey-abc",
        claude_token="sk-ant-xyz",
        repo="repo",
    )
    assert env["PATH"] == "/usr/bin"
    assert env["DEVBOX_HOST"] == "acme-repo.exe.xyz"
    assert env["DEVBOX_TS_AUTHKEY"] == "tskey-abc"
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "sk-ant-xyz"
    assert env["DEVBOX_REPO"] == "repo"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_provision.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `devbox/provision.py`**

```python
"""Invoke the pyinfra deploy, passing secrets via environment only."""
from __future__ import annotations

import subprocess

INVENTORY = "deploy/inventory.py"
DEPLOY = "deploy/deploy.py"


def build_pyinfra_args() -> list[str]:
    return ["pyinfra", INVENTORY, DEPLOY]


def build_env(base: dict, *, host: str, ts_key: str, claude_token: str,
              repo: str) -> dict:
    env = dict(base)
    env["DEVBOX_HOST"] = host
    env["DEVBOX_TS_AUTHKEY"] = ts_key
    env["CLAUDE_CODE_OAUTH_TOKEN"] = claude_token
    env["DEVBOX_REPO"] = repo
    return env


def run_pyinfra(env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(build_pyinfra_args(), env=env, check=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_provision.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add devbox/provision.py tests/test_provision.py
git commit -m "feat: pyinfra invocation with secrets via env"
```

---

### Task 7: pyinfra deploy — inventory + operations (`deploy/`)

**Files:**
- Create: `deploy/inventory.py`
- Create: `deploy/deploy.py`
- Test: verified via `pyinfra --dry` (no unit test — infra operations).

**Interfaces:**
- Consumes (from environment, set by Task 6): `DEVBOX_HOST`, `DEVBOX_TS_AUTHKEY`,
  `CLAUDE_CODE_OAUTH_TOKEN`, `DEVBOX_REPO`.
- Produces: a provisioned VM. No Python symbols consumed by other tasks.

> **Verification risks flagged in the spec (handle here):**
> 1. pyinfra's paramiko SSH connector vs. exe.dev host keys/`.exe.xyz`. The
>    inventory sets `ssh_strict_host_key_checking="accept-new"` and reads the
>    user's `~/.ssh/config`. If connection fails, fall back to the system ssh by
>    setting per-host `ssh_...` data — confirm during the dry run.
> 2. `claude plugin install` idempotency — wrapped so re-install is a no-op.
> 3. herdr detached-session CLI — the exact flags are confirmed against
>    `herdr --help` in Task 8; this task only installs herdr.

- [ ] **Step 1: Write the inventory**

`deploy/inventory.py`:
```python
"""pyinfra inventory: single exe.dev host, data pulled from the environment."""
import os

_host = os.environ["DEVBOX_HOST"]

hosts = [
    (
        _host,
        {
            "ts_authkey": os.environ["DEVBOX_TS_AUTHKEY"],
            "claude_token": os.environ["CLAUDE_CODE_OAUTH_TOKEN"],
            "repo": os.environ["DEVBOX_REPO"],
            # Let paramiko use the user's ssh config and trust first-seen keys,
            # matching the manual `ssh <name>.exe.xyz` flow.
            "ssh_strict_host_key_checking": "accept-new",
        },
    )
]
```

- [ ] **Step 2: Write the deploy operations**

`deploy/deploy.py`:
```python
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
```

- [ ] **Step 3: Dry-run to verify the plan compiles and connects**

Set env for a throwaway VM you control (create one first via `ssh exe.dev new`
or reuse one), then:

Run:
```bash
DEVBOX_HOST=<name>.exe.xyz \
DEVBOX_TS_AUTHKEY=tskey-dummy \
CLAUDE_CODE_OAUTH_TOKEN=sk-ant-dummy \
DEVBOX_REPO=<repo> \
uv run pyinfra deploy/inventory.py deploy/deploy.py --dry -v
```
Expected: pyinfra connects over SSH and prints a change plan with **no Python
errors**. If the SSH connection fails, apply verification-risk #1 (adjust the
inventory's ssh data) and re-run until the dry plan renders.

- [ ] **Step 4: Real apply + idempotency check**

Run the same command **without** `--dry` twice (against a real scratch VM, with a
real Tailscale key and a repo whose integration is attached):
```bash
# ... same env ... uv run pyinfra deploy/inventory.py deploy/deploy.py -v
```
Expected: first run applies changes; the **second run reports no changes** for
`apt.packages`, `files.line`, and `git.repo`, and the guarded shells no-op.
Fix any operation that reports changes on the second run before committing.

- [ ] **Step 5: Commit**

```bash
git add deploy/inventory.py deploy/deploy.py
git commit -m "feat: pyinfra deploy for devbox provisioning"
```

---

### Task 8: Orchestrator CLI + detached claude session (`devbox/cli.py`, `devbox.py`)

**Files:**
- Create: `devbox/cli.py`
- Create: `devbox.py` (thin shim: `from devbox.cli import main; main()`)
- Create: `devbox/session.py`
- Test: `tests/test_cli.py`, `tests/test_session.py`

**Interfaces:**
- Consumes: `config`, `exe`, `tailscale`, `claude_auth`, `provision`.
- Produces:
  - `session.build_start_session_cmd(repo: str) -> str` — the shell command run
    over SSH to start a detached herdr session named `devbox` running claude.
  - `session.session_exists_cmd(name: str) -> str` — shell command that exits 0
    if a herdr session named `name` already exists.
  - `cli.parse_args(argv: list[str]) -> argparse.Namespace` — positional
    `user/repo`, optional `--prefix`.
  - `cli.split_repo(spec: str) -> tuple[str, str]` — split `"user/repo"`.
  - `cli.preflight() -> list[str]` — returns a list of missing prerequisites
    (empty = OK): checks `ssh`, `claude`, and `git` are on PATH.
  - `cli.main(argv=None) -> int`.

> **Verification risk (herdr CLI):** `build_start_session_cmd` /
> `session_exists_cmd` below are the best-effort herdr invocation. In Step 3
> confirm the exact subcommands against `ssh <host> herdr --help` on a live VM
> and adjust the command strings if they differ. The unit tests assert on our
> chosen command strings, so update tests and code together if the CLI differs.

- [ ] **Step 1: Write failing tests for session + cli helpers**

`tests/test_session.py`:
```python
from devbox import session


def test_start_session_cmd_is_detached_and_named():
    cmd = session.build_start_session_cmd("myrepo")
    assert "herdr" in cmd
    assert "devbox" in cmd            # session name
    assert "myrepo" in cmd            # working dir
    assert "claude rc" in cmd
    assert "bypassPermissions" in cmd


def test_session_exists_cmd_names_session():
    assert "devbox" in session.session_exists_cmd("devbox")
```

`tests/test_cli.py`:
```python
import pytest

from devbox import cli


def test_split_repo():
    assert cli.split_repo("me/widgets") == ("me", "widgets")


def test_split_repo_rejects_bad_input():
    with pytest.raises(ValueError):
        cli.split_repo("noslash")


def test_parse_args_prefix_optional():
    ns = cli.parse_args(["me/widgets", "--prefix", "acme"])
    assert ns.repo_spec == "me/widgets"
    assert ns.prefix == "acme"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_session.py tests/test_cli.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `devbox/session.py`**

```python
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
```

- [ ] **Step 4: Implement `devbox/cli.py` and `devbox.py`**

`devbox/cli.py`:
```python
"""devbox orchestrator: create exe.dev integration + VM, provision via pyinfra."""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time

import httpx

from devbox import claude_auth, config, exe, provision, session, tailscale

ACCOUNT_REQUIRED = ["ts_oauth_client_id", "ts_oauth_client_secret",
                    "ts_tailnet", "ts_tag"]
REPO_REQUIRED = ["github_user", "repo_name", "exe_prefix"]


def split_repo(spec: str) -> tuple[str, str]:
    if "/" not in spec:
        raise ValueError(f"expected user/repo, got: {spec!r}")
    user, repo = spec.split("/", 1)
    if not user or not repo:
        raise ValueError(f"expected user/repo, got: {spec!r}")
    return user, repo


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="devbox")
    p.add_argument("repo_spec", help="GitHub repo as user/repo")
    p.add_argument("--prefix", help="exe.dev VM name prefix")
    return p.parse_args(argv)


def preflight() -> list[str]:
    return [tool for tool in ("ssh", "claude", "git")
            if shutil.which(tool) is None]


def _prompt(field: str, secret: bool = False) -> str:
    import questionary
    ask = questionary.password if secret else questionary.text
    return ask(f"{field}: ").ask()


def _resolve_repo_config(user, repo, prefix) -> dict:
    cached = config.load_toml(config.repo_config_path(repo))
    cli_layer = {"github_user": user, "repo_name": repo, "exe_prefix": prefix}
    merged = config.merge(cached, cli_layer)
    for field in config.missing_fields(merged, REPO_REQUIRED):
        merged[field] = _prompt(field)
    config.save_toml(config.repo_config_path(repo), merged)
    return merged


def _resolve_account_config() -> dict:
    acct = config.load_toml(config.ACCOUNT_PATH)
    changed = False
    for field in config.missing_fields(acct, ACCOUNT_REQUIRED):
        acct[field] = _prompt(field, secret=field.endswith("secret"))
        changed = True
    if changed:
        config.save_toml(config.ACCOUNT_PATH, acct)
    return acct


def _ssh_ready(host: str) -> bool:
    result = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", host, "true"],
        capture_output=True,
    )
    return result.returncode == 0


def _wait_for_ssh(host: str, timeout=300) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _ssh_ready(host):
            return
        time.sleep(5)
    raise TimeoutError(f"SSH to {host} not ready within {timeout}s")


def main(argv=None) -> int:
    ns = parse_args(sys.argv[1:] if argv is None else argv)
    missing = preflight()
    if missing:
        print(f"Missing required tools on PATH: {', '.join(missing)}",
              file=sys.stderr)
        return 1

    user, repo = split_repo(ns.repo_spec)
    account = _resolve_account_config()
    repo_cfg = _resolve_repo_config(user, repo, ns.prefix)

    # Claude token (local browser login once), cached in account config.
    token = claude_auth.ensure_token(account.get("claude_token"))
    if token != account.get("claude_token"):
        account["claude_token"] = token
        config.save_toml(config.ACCOUNT_PATH, account)

    name = f"{repo_cfg['exe_prefix']}-{repo}"
    host = exe.vm_host(repo_cfg["exe_prefix"], repo)

    # exe.dev integration (create-if-missing).
    if not exe.integration_exists(exe.list_integrations(), repo):
        print(f"Creating GitHub integration for {user}/{repo}...")
        exe.add_integration(user, repo)

    # exe.dev VM (create-if-missing).
    if not exe.vm_exists(exe.list_vms(), name):
        print(f"Creating VM {name}...")
        exe.create_vm(name, ["dev", repo])

    print(f"Waiting for SSH to {host}...")
    _wait_for_ssh(host)

    # Fresh ephemeral Tailscale key per run.
    print("Minting Tailscale auth key...")
    with httpx.Client(base_url=tailscale.TS_API, timeout=30) as client:
        ts_key = tailscale.mint_key(
            account["ts_tailnet"], account["ts_tag"],
            account["ts_oauth_client_id"], account["ts_oauth_client_secret"],
            client=client,
        )

    # Provision via pyinfra (secrets via env).
    print("Provisioning via pyinfra...")
    env = provision.build_env(dict(os.environ), host=host, ts_key=ts_key,
                              claude_token=token, repo=repo)
    provision.run_pyinfra(env)

    # Start detached claude session (idempotent).
    print("Starting detached claude session...")
    subprocess.run(["ssh", host, session.build_start_session_cmd(repo)],
                   check=True)

    print(f"Done. Connect with:  ssh {host} herdr attach devbox")
    return 0
```

`devbox.py`:
```python
#!/usr/bin/env python
from devbox.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run unit tests**

Run: `uv run pytest tests/test_session.py tests/test_cli.py -v`
Expected: PASS.

- [ ] **Step 6: Verify herdr session command against a live VM**

Run: `ssh <scratch-host> herdr --help` and confirm `herdr list`, `herdr new -d
-s <name> -c <dir> -- <cmd>`, and `herdr attach <name>` are correct. If the CLI
differs, update `devbox/session.py` **and** `tests/test_session.py` together and
re-run Step 5.

- [ ] **Step 7: Commit**

```bash
git add devbox/cli.py devbox/session.py devbox.py tests/test_cli.py tests/test_session.py
git commit -m "feat: orchestrator CLI and detached claude session"
```

---

### Task 9: Full smoke test, README, and remove bash scripts

**Files:**
- Modify: `README.md`
- Delete: `add-repo.sh`, `create-vm.sh`, `setup-vm.sh`

**Interfaces:**
- Consumes: everything above.
- Produces: documented, end-to-end-verified tool; old scripts removed.

- [ ] **Step 1: End-to-end smoke test**

Against a scratch GitHub repo you own, from a clean state (no `.devbox/<repo>.toml`):
```bash
uv run devbox.py <you>/<scratch-repo> --prefix <your-prefix>
```
Expected: prompts for any missing account/repo config, creates the integration
and VM (or reports them existing), provisions without error, and finishes with
the "Connect with" line. Then:
```bash
ssh <prefix>-<repo>.exe.xyz herdr attach devbox
```
Expected: a live `claude` session in `~/<repo>`, already authenticated (no login
prompt).

- [ ] **Step 2: Idempotency re-run**

Run the exact same `uv run devbox.py ...` command again.
Expected: integration and VM reported as existing, pyinfra second run reports no
changes, and the claude session is **not** duplicated. Note any step that is not
idempotent and fix it before proceeding.

- [ ] **Step 3: Rewrite `README.md`**

Replace the body with usage for the new tool. Required content:
- Prerequisites: exe.dev account with SSH key; `uv`; `claude` CLI installed
  locally; Tailscale account.
- **One-time Tailscale setup:** create an OAuth client (scope: Devices → Auth
  Keys, write) and add the tag (e.g. `tag:devbox`) with an `autoApprovers`/owner
  entry in the tailnet ACL. Put the client id/secret, tailnet, and tag into
  `~/.config/devbox/config.toml` (or let the first run prompt for them).
- **One-time Claude setup:** the first run invokes `claude setup-token` and
  opens a browser locally; the token is cached in `~/.config/devbox/config.toml`.
- Usage: `uv run devbox.py <user>/<repo> [--prefix <prefix>]`.
- Connect: `ssh <prefix>-<repo>.exe.xyz herdr attach devbox`.
- Note that `.devbox/` is gitignored and holds per-repo config.
- Keep the existing "personal use / reference only" note and the tool list.

- [ ] **Step 4: Remove the old scripts**

```bash
git rm add-repo.sh create-vm.sh setup-vm.sh
```

- [ ] **Step 5: Full test suite + commit**

Run: `uv run pytest -v`
Expected: all unit tests PASS.
```bash
git add README.md
git commit -m "docs: rewrite README for pyinfra devbox; remove bash scripts"
```

---

## Self-Review Notes

- **Spec coverage:** architecture (Tasks 6–8), Tailscale OAuth key (Task 4), Claude local token (Task 5), detached herdr session (Task 8), config/secrets split (Task 2, wired in Task 8), create-if-missing integration+VM (Tasks 3, 8), pyinfra idempotent ops (Task 7), preflight/error handling (Task 8), testing incl. dry-run + idempotency (Tasks 7, 9). All spec sections map to a task.
- **Flagged verification points carried from the spec into concrete steps:** exe.dev JSON shape (Task 3 note + Task 8 live run), pyinfra↔exe.dev SSH (Task 7 Step 3), `claude plugin install` idempotency (Task 7, `|| true` + Task 9 Step 2), `claude setup-token` output format (Task 5 note), herdr CLI (Task 8 Step 6).
- **Secret hygiene:** secrets flow through env/files only (Task 6 test asserts no secrets in argv).
```
