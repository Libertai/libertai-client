import os
import zipfile

from pathspec import pathspec

from libertai_client.interfaces.agent import AgentConfig
from libertai_client.utils.system import get_full_path


def parse_agent_config_env(env: dict[str, str | None]) -> AgentConfig:
    agent_id = env.get("LIBERTAI_AGENT_ID", None)
    agent_secret = env.get("LIBERTAI_AGENT_SECRET", None)

    if agent_id is None or agent_secret is None:
        raise EnvironmentError(
            f"Missing {'LIBERTAI_AGENT_ID' if agent_id is None else 'LIBERTAI_AGENT_SECRET'} variable in your project's .env.libertai"
        )

    return AgentConfig(id=agent_id, secret=agent_secret)


AGENT_ZIP_BLACKLIST = [".git", ".idea", ".vscode"]
AGENT_ZIP_WHITELIST = [".env"]


def create_agent_zip(src_dir: str, zip_name: str):
    # Read and parse the .gitignore file
    with open(get_full_path(src_dir, ".gitignore"), "r") as gitignore_file:
        gitignore_patterns = gitignore_file.read()
    spec = pathspec.PathSpec.from_lines(
        "gitwildmatch", gitignore_patterns.splitlines() + AGENT_ZIP_BLACKLIST
    )

    with zipfile.ZipFile(zip_name, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, _, files in os.walk(src_dir):
            for file in files:
                file_path = os.path.join(root, file)
                relative_path = os.path.relpath(file_path, src_dir)

                # Check if the file matches any .gitignore pattern
                if (
                    not spec.match_file(relative_path)
                    or relative_path in AGENT_ZIP_WHITELIST
                ):
                    zipf.write(file_path, arcname=relative_path)
