#/bin/bash

set -o nounset
set -o errexit
set -o pipefail

# Define helper functions
# used for consistent prefix in script logging
log() {
  echo "[LOG] $1"
}
# used to abort the script if there's an error
abort() {
  log "Aborting script at $(date +%c)"
  exit 321
}
# If cleanup is needed, use a cleanup trap
cleanup() {
  log "Script exiting with code $?"
}
trap cleanup EXIT

# Copy stdout+stderr to the syslog (not needed since exe.dev setup scripts do this already)
# exec >  >(logger -s)
# exec 2> >(logger -s >&2)
log "[$(date +%c)] Script starting..."

# Installing generic deps
sudo apt install -y mosh nnn fzf fd
echo "export EDITOR=vim" >> ~/.bashrc

# Mise installation
sudo apt install -y extrepo
sudo extrepo enable mise
sudo apt update -y
sudo apt install -y mise
echo 'eval "$(mise activate bash)"' >> ~/.bashrc

# lazygit
LAZYGIT_VERSION=$(curl -s "https://api.github.com/repos/jesseduffield/lazygit/releases/latest" | \grep -Po '"tag_name": *"v\K[^"]*')
LAZYGIT_ARCH=$(uname -m | sed -e 's/aarch64/arm64/')
curl -Lo lazygit.tar.gz "https://github.com/jesseduffield/lazygit/releases/download/v${LAZYGIT_VERSION}/lazygit_${LAZYGIT_VERSION}_Linux_${LAZYGIT_ARCH}.tar.gz"
tar xf lazygit.tar.gz lazygit
sudo install lazygit -D -t /usr/local/bin/

# herdr
curl -fsSL https://herdr.dev/install.sh | sh

# nnn config
sh -c "$(curl -Ls https://raw.githubusercontent.com/jarun/nnn/master/plugins/getplugs)"
echo "export NNN_PLUG='o:fzopen'" >> ~/.bashrc


# Tailscale
sudo systemctl start tailscaled

# NOTE: this step blocks on user input
sudo tailscale up

sudo tailscale set --ssh

# Github setup / clone repo
echo "export GH_HOST=github.int.exe.xyz" >> ~/.bashrc
INTEGRATIONS="$(curl -s https://reflection.int.exe.xyz/integrations)"
$(echo "$INTEGRATIONS" | jq -r '.integrations[] | select(.type == "github") | .help')
REPO="$(echo "$INTEGRATIONS" | jq -r '.integrations[] | select(.type == "github") | .name')"
cd "$REPO"

claude plugin marketplace add obra/superpowers-marketplace
claude plugin install superpowers@superpowers-marketplace
claude plugin install elements-of-style@superpowers-marketplace
claude plugin install double-shot-latte@superpowers-marketplace
claude plugin install superpowers-chrome@superpowers-marketplace
claude plugin install frontend-design@claude-plugins-official