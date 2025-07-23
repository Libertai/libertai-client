import os


class _Config:
    AGENTS_BACKEND_URL: str
    DEPLOY_SCRIPT_URL: str

    def __init__(self):
        self.AGENTS_BACKEND_URL = os.getenv(
            "LIBERTAI_CLIENT_BACKEND_URL", "https://inference.api.libertai.io"
        )
        self.DEPLOY_SCRIPT_URL = os.getenv(
            "LIBERTAI_CLIENT_DEPLOY_SCRIPT_URL",
            "https://raw.githubusercontent.com/Libertai/libertai-agents/refs/heads/main/deployment/deploy.sh",
        )


config = _Config()
