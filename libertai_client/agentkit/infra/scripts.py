DEPLOY_CODE_SCRIPT = r"""#!/bin/bash
set -euo pipefail
rm -rf /opt/libertai-agentkit
mkdir -p /opt/libertai-agentkit
tar xzf /tmp/libertai-agentkit.tar.gz -C /opt/libertai-agentkit
"""

INSTALL_DOCKER_SCRIPT = r"""#!/bin/bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
curl -fsSL https://get.docker.com | sh
"""

START_AGENT_SCRIPT = r"""#!/bin/bash
set -euo pipefail
cd /opt/libertai-agentkit
docker compose up -d --build
"""
