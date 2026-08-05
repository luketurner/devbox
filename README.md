# Devbox setup

Scripts and notes for setting up a VM for agentic development in the cloud.

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

Dependencies:

1. exe.dev account with Github integration set up.
2. Local SSH key that has full privileges in your exe.dev account.
3. Tailscale account.

Usage:

1. Set environment variables.
2. Run scripts.
3. Take any manual steps as documented below.

```bash
export GITHUB_USER="me"
export REPO_NAME="my-repo"
export EXE_PREFIX="my-unique-prefix"

# run once per Github repo
./add-repo.sh

# run to create new VM for github repo and open the setup script logs on the server.
# you'll need to click the Tailscale link in the logs and login in your browser for
# the script to be able to complete.
./create-vm.sh

# run the following in herdr:
claude # login, trust workspace, and exit.
claude rc --permission-mode=bypassPermissions --spawn=same-dir

# then detach the session with C-b q
```