# Dockerfile: Sandboxed Agent Environment
# Provides an isolated, unprivileged execution environment matching host user/agent UID.
# ==============================================================================
FROM ubuntu:22.04

# Avoid interactive prompts during apt install
ENV DEBIAN_FRONTEND=noninteractive

# Install core developer utilities and networking tools
RUN apt-get update && apt-get install -y \
    curl \
    git \
    python3 \
    python3-pip \
    python3.11 \
    python3.11-venv \
    python3.11-distutils \
    sudo \
    nano \
    vim \
    iproute2 \
    net-tools \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Customizable UID/GID (defaults to 1001)
ARG AGENT_UID=1001
ARG AGENT_GID=1001

# Create group 'agent' and user 'agent'
RUN groupadd -g ${AGENT_GID} agent 2>/dev/null || groupadd agent && \
    useradd -u ${AGENT_UID} -g agent -m -s /bin/bash agent 2>/dev/null || useradd -g agent -m -s /bin/bash agent

# Configure passwordless sudo INSIDE the container for the agent user.
# (If 'allow_sudo' is false in settings, the orchestrator mounts /dev/null over /usr/bin/sudo, disabling this completely).
RUN echo "agent ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/agent && \
    chmod 0440 /etc/sudoers.d/agent

# Define persistent workspace and scratch paths
RUN mkdir -p /workspace /scratch && \
    chown -R agent:agent /workspace /scratch

# Set default working directory
WORKDIR /workspace

# Switch context to the unprivileged agent user
USER agent

# Default command to run
CMD ["bash"]
