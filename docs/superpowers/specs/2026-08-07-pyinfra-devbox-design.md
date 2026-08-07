# Devbox: pyinfra rewrite — design

**Date:** 2026-08-07
**Status:** Approved (pending spec review)

## Goal

Replace the current bash scripts (`add-repo.sh`, `create-vm.sh`, `setup-vm.sh`)
with a single, idempotent Python entrypoint. A user should be able to:

1. Create a new repository in GitHub (out of scope for this tool).
2. Run one command — `uv run devbox.py <github-user/repo>` — that prompts for any
   missing information, creates the exe.dev GitHub integration for the repo,
   creates an exe.dev VM for the repo, and provisions it so a live `claude`
   session is waiting for the user to connect.

Provisioning must be fully unattended: **no browser interaction and no
copy/pasting of URLs or tokens during a run**, and the whole flow must be
idempotent (safe to re-run to converge an existing VM).

## Decisions (locked)

- **Architecture:** pyinfra-over-SSH. `devbox.py` creates a *bare* exe.dev VM
  and provisions it by running a pyinfra deploy over SSH from the user's
  machine. exe.dev's first-boot `--setup-script` is **not** used for
  provisioning — pyinfra owns it. This is the idiomatic pyinfra model and the
  only option that delivers convergent idempotency.
- **Tailscale auth:** OAuth-client / ephemeral key. `devbox.py` mints a fresh
  ephemeral, pre-authorized, tagged auth key per run via the Tailscale API using
  stored OAuth client credentials, then `tailscale up --auth-key=... --ssh`. No
  browser.
- **Claude auth:** local `claude setup-token`. The browser login runs once on
  the user's laptop (where the OAuth loopback redirect works reliably), the
  resulting long-lived token is cached locally, and injected into every VM as
  `CLAUDE_CODE_OAUTH_TOKEN`. No browser or copy/paste on the VM. (The remote
  login + SSH port-forward alternative was rejected: it only works if Claude
  Code picks loopback mode on a headless box, which is unreliable and can fall
  back to copy/paste.)
- **End state:** VM provisioned **and** a `claude` session already running,
  detached, in a herdr session — so a live session is waiting when the user
  connects.
- **Local runtime:** `uv` with a `pyproject.toml`.
- **Config/secrets split:** account-level config/secrets in
  `~/.config/devbox/config.toml`; per-repo config in a gitignored
  `.devbox/<repo>.toml`. Secrets are never committed.

## Local tool layout

```
pyproject.toml          # uv-managed; deps: pyinfra, httpx, questionary
devbox.py               # CLI entrypoint / orchestrator
devbox/
  config.py             # load/merge account + per-repo config, prompt, cache
  exe.py                # wrappers over `ssh exe.dev ...` (--json), idempotency checks
  tailscale.py          # OAuth client-credentials -> mint ephemeral pre-auth key
  claude_auth.py        # ensure `claude setup-token` cached locally
  provision.py          # invoke pyinfra as a subprocess, pass secrets via env
deploy/
  inventory.py          # single host: <prefix>-<repo>.exe.xyz, reads data from env
  deploy.py             # pyinfra operations
README.md               # updated usage + one-time setup docs
```

### Config & secrets

- **Account-level** — `~/.config/devbox/config.toml`:
  - Tailscale: OAuth client id/secret, tailnet, tag (e.g. `tag:devbox`).
  - Cached Claude token (`CLAUDE_CODE_OAUTH_TOKEN`).
- **Per-repo** — `.devbox/<repo>.toml` (gitignored): GitHub `user/repo`, exe VM
  name prefix. Prompted on first run, cached thereafter.
- CLI args override cached values; anything still missing is prompted
  interactively (via `questionary`) and then cached.

## `devbox.py` orchestration flow

All steps are create-if-missing / idempotent.

1. **Resolve config** — merge account config + per-repo config + CLI args;
   prompt for anything missing; cache per-repo answers.
2. **Ensure secrets** — if no cached Claude token, run `claude setup-token`
   locally (browser login on the laptop) and cache it. Verify Tailscale OAuth
   credentials are present.
3. **exe.dev GitHub integration** — `ssh exe.dev integrations list --json`;
   create with `integrations add github --name <repo> --repository
   <user>/<repo> --attach tag:<repo>` only if absent.
4. **exe.dev VM** — `ssh exe.dev ls --json`; create with `ssh exe.dev new
   --name <prefix>-<repo> --tag dev --tag <repo>` only if absent. Bare VM (no
   provisioning setup script).
5. **Wait for SSH** — poll `<prefix>-<repo>.exe.xyz` until reachable (bounded
   timeout).
6. **Mint Tailscale key** — POST to the Tailscale API with OAuth client
   credentials to create an ephemeral, pre-authorized, tagged auth key (fresh
   per run).
7. **Run pyinfra** — `provision.py` shells out to `pyinfra deploy/inventory.py
   deploy/deploy.py`, passing the Tailscale key, Claude token, and repo name via
   **environment variables** (not argv, to avoid `ps` leakage).
8. **Start detached claude session** — run `claude rc
   --permission-mode=bypassPermissions --spawn=same-dir` inside a herdr session
   and detach; guarded so a re-run does not spawn a duplicate.

## pyinfra deploy (`deploy.py`) operations

- **Packages** — `apt.packages`: mosh, nnn, fzf, fd-find, extrepo; then mise via
  extrepo. Natively idempotent.
- **Shell config** — `files.line` / `files.block` for the `~/.bashrc` entries
  (`EDITOR`, `mise activate`, `GH_HOST`, `NNN_PLUG`). Idempotent, unlike the
  current `>>` appends which duplicate on re-run.
- **lazygit** — download + install, guarded by a version check (no-op when
  current).
- **herdr** — install script, guarded on binary presence.
- **nnn plugins** — `getplugs`.
- **Tailscale** — ensure installed; `systemctl start tailscaled`; `tailscale up
  --auth-key=<key> --ssh` + `tailscale set --ssh`, guarded on `tailscale
  status`.
- **GitHub repo** — set `GH_HOST=github.int.exe.xyz`; clone via `git.repo`
  (idempotent) using the reflection-provided integration name.
- **Claude** — `claude plugin marketplace add obra/superpowers-marketplace` and
  the plugin installs (superpowers, elements-of-style, double-shot-latte,
  superpowers-chrome, frontend-design); write `CLAUDE_CODE_OAUTH_TOKEN` to a
  persisted env file so the detached session and future logins are
  authenticated.

## Error handling & preflight

- Preflight checks **before creating anything**: `ssh exe.dev` reachable, local
  `claude` CLI present, Tailscale OAuth creds present. Fail fast with clear
  messages.
- exe.dev and Tailscale calls check exit codes and parse `--json`.
- SSH-wait and API calls use bounded retries.
- Partial failures are recoverable by re-running (idempotent).

## Idempotency

**Naturally idempotent:** all `apt.packages`, `files.line`/`files.block`,
`git.repo`, create-if-missing for integration and VM, `tailscale up` with a key.

**Guarded (implemented, flagged as not free):**
- lazygit / herdr installs — guarded on version/binary presence.
- `claude plugin install` — idempotency uncertain; guard by checking the
  installed list or tolerating "already installed". ⚠️ **Needs empirical
  verification.**
- Detached herdr claude session — guarded by checking for an existing named
  session (else re-runs spawn duplicates).
- Tailscale key minting — a fresh ephemeral key is minted every run by design;
  harmless but not reused.

**Verification risks:**
- pyinfra's paramiko SSH connector vs. exe.dev host keys / `.exe.xyz` hostnames —
  confirm it connects cleanly; may require pointing pyinfra at the user's ssh
  config / known_hosts. ⚠️
- Tailscale OAuth one-time setup — the user must create an OAuth client and a tag
  in their tailnet ACL once. Documented in the README.

## Testing

- **Pure logic** (config merge, exe.dev/Tailscale wrappers) — unit tests with
  mocked subprocess/HTTP.
- **Provisioning** — `pyinfra --dry` for the plan, plus an **idempotency test**:
  run the deploy twice against a throwaway VM and assert the second run reports
  zero changes.
- **Smoke test** — full `devbox.py` run against a scratch repo/VM, verified by
  connecting and seeing the live claude session.

## Out of scope

- Creating the GitHub repository itself.
- Tearing down / deleting VMs and integrations (may be a later addition).
```
