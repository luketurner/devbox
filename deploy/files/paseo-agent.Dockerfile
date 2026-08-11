# Guest image for Paseo agents running inside a smolvm microVM. smolvm takes
# OCI images but bundles no agent CLIs, so this adds claude on top of node.
# Built on the box and `docker save`d to a tar: a bare --image name is always
# a registry reference, so a locally built image must be passed as an archive.
FROM node:22-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g @anthropic-ai/claude-code
