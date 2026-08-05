#/bin/bash

set -euo pipefail

ssh exe.dev integrations add github \
--name "$REPO_NAME" \
--repository "$GITHUB_USER"/"$REPO_NAME" \
--attach "tag:$REPO_NAME"