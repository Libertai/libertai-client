import os


class _Config:
    AGENTS_BACKEND_URL: str

    def __init__(self):
        self.AGENTS_BACKEND_URL = os.getenv("LIBERTAI_CLIENT_AGENTS_BACKEND_URL",
                                            "https://e6cd-58-142-26-96.ngrok-free.app")


config = _Config()
