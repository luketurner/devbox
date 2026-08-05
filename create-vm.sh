#/bin/bash

set -euo pipefail

cat setup.sh | ssh exe.dev new \
--name "$EXE_PREFIX-$REPO_NAME" \
--tag dev \
--tag "$REPO_NAME" \
--setup-script /dev/stdin

ssh "$EXE_PREFIX-$REPO_NAME.exe.xyz" journalctl -f

ssh "$EXE_PREFIX-$REPO_NAME.exe.xyz" herdr