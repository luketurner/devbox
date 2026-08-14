# Guest image for Paseo agents running inside a smolvm microVM.
#
# Plain Debian rather than a language base image: projects bring their own
# toolchains, so baking in node would just be one opinionated choice out of
# many. smolvm supplies the kernel via libkrun; this only provides userspace.
FROM debian:trixie-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        gh \
        git \
        # agent-entry reads the default gateway to find the devbox.
        iproute2 \
    && rm -rf /var/lib/apt/lists/*

# Route gh through the exe.dev integration rather than github.com. Constant, so
# it belongs in the image rather than in the launch wrapper.
ENV GH_HOST=github.int.exe.xyz

# Native installer rather than the deprecated npm package. It refuses to run
# under sudo but plain root is fine, and it installs under $HOME.
RUN curl -fsSL https://claude.ai/install.sh | bash
ENV PATH="/root/.local/bin:$PATH"

# Plugins are baked in rather than installed on the devbox: the microVM mounts
# only the workspace, so the host's ~/.claude is invisible in here. Tolerant of
# failure, matching how these were installed host-side — a flaky marketplace
# fetch should degrade the image, not brick a whole provision.
# claude-plugins-official is preconfigured on a desktop install but not in a
# fresh container, so add it explicitly alongside the third-party one.
RUN claude plugin marketplace add obra/superpowers-marketplace || true
RUN claude plugin marketplace add anthropics/claude-plugins-official || true
COPY agent-entry /usr/local/bin/agent-entry
RUN chmod +x /usr/local/bin/agent-entry

RUN for plugin in \
        superpowers@superpowers-marketplace \
        elements-of-style@superpowers-marketplace \
        double-shot-latte@superpowers-marketplace \
        superpowers-chrome@superpowers-marketplace \
        frontend-design@claude-plugins-official \
    ; do claude plugin install "$plugin" || true; done
