# Devbox setup

A small pyinfra-based tool for setting up a VM for agentic development in the cloud.

> [!NOTE]
> This tool is meant for personal use, and made available online for example / reference purposes only. Please fork and edit yourself if you want to adjust anything.

Stack:

- exe.dev VM
- Tailscale

Creates a "devbox" VM with extra installed tools (above what comes with exeuntu by default):

- fzf
- mosh
- mise
- nnn
- lazygit
- herdr
- tailscale (w/ssh)
- claude plugins

## Prerequisites

- An exe.dev account with an SSH key that has full privileges to create VMs
  and integrations.
- [`uv`](https://docs.astral.sh/uv/).
- The `claude` CLI installed locally.
- A Tailscale account.

## One-time Tailscale setup

Create a Tailscale OAuth client with scope `Devices > Auth Keys` (write), and
define a tag (e.g. `tag:devbox`) with an appropriate owner/`autoApprovers`
entry in your tailnet ACL so the devbox VM can join automatically.

Put the OAuth client id/secret, tailnet, and tag into
`~/.config/devbox/config.toml`:

```toml
ts_oauth_client_id = "..."
ts_oauth_client_secret = "..."
ts_tailnet = "..."
ts_tag = "tag:devbox"
```

Or just leave them out — the first run will prompt for any missing values and
save them there for you.

## One-time Claude setup

The first run invokes `claude setup-token`, which opens a browser locally for
you to authenticate. The resulting token is cached in
`~/.config/devbox/config.toml` so subsequent runs don't need to log in again.

## Usage

```bash
uv run devbox.py <user>/<repo> [--prefix <prefix>]
```

This creates the exe.dev GitHub integration and VM if they don't already
exist, provisions the VM via pyinfra, and starts a detached `claude` session
for the repo.

Once it finishes, connect with:

```bash
ssh <prefix>-<repo>.exe.xyz herdr attach devbox
```

## Config

Per-repo config is cached under `.devbox/` (gitignored) in the current
directory, so re-running `uv run devbox.py <user>/<repo>` picks up the same
prefix and settings without prompting again.
