import json
import os
import zipfile
from enum import Enum
from typing import Annotated

import aiohttp
import pathspec
import rich
import typer
from dotenv import dotenv_values
from libertai_utils.interfaces.agent import UpdateAgentResponse
from rich.console import Console

from libertai_client.config import config
from libertai_client.utils.agent import parse_agent_config_env
from libertai_client.utils.system import get_full_path
from libertai_client.utils.typer import AsyncTyper

app = AsyncTyper(name="agent", help="Deploy and manage agents")

err_console = Console(stderr=True)

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


class AgentPythonPackageManager(str, Enum):
    poetry = "poetry"
    pip = "pip"


class AgentUsageType(str, Enum):
    fastapi = "fastapi"
    python = "python"


@app.command()
async def deploy(
    path: Annotated[
        str, typer.Option(help="Path to the root of your repository", prompt=True)
    ] = ".",
    python_version: Annotated[
        str, typer.Option(help="Version to deploy with", prompt=True)
    ] = "3.11",
    package_manager: Annotated[
        AgentPythonPackageManager, typer.Option(case_sensitive=False, prompt=True)
    ] = AgentPythonPackageManager.pip.value,  # type: ignore
    usage_type: Annotated[
        AgentUsageType, typer.Option(case_sensitive=False, prompt=True)
    ] = AgentUsageType.fastapi.value,  # type: ignore
):
    """
    Deploy or redeploy an agent
    """

    # TODO: try to detect package manager, show detected value and ask user for the confirmation or change
    # Same for python version

    # TODO: allow user to give a custom deployment script URL

    try:
        libertai_env_path = get_full_path(path, ".env.libertai")
        libertai_config = parse_agent_config_env(dotenv_values(libertai_env_path))
    except (FileNotFoundError, EnvironmentError) as error:
        err_console.print(f"[red]{error}")
        raise typer.Exit(1)

    agent_zip_path = "/tmp/libertai-agent.zip"

    create_agent_zip(path, agent_zip_path)

    data = aiohttp.FormData()
    data.add_field("secret", libertai_config.secret)
    data.add_field("python_version", python_version)
    data.add_field("package_manager", package_manager.value)
    data.add_field("usage_type", usage_type.value)
    data.add_field("code", open(agent_zip_path, "rb"), filename="libertai-agent.zip")

    async with aiohttp.ClientSession() as session:
        async with session.put(
            f"{config.AGENTS_BACKEND_URL}/agent/{libertai_config.id}",
            headers={"accept": "application/json"},
            data=data,
        ) as response:
            if response.status == 200:
                response_data = UpdateAgentResponse(**json.loads(await response.text()))  # noqa: F821
                # TODO: don't show /docs if deployed in python mode
                rich.print(
                    f"[green]Agent successfully deployed on http://[{response_data.instance_ip}]:8000/docs"
                )
            else:
                error_message = await response.text()
                err_console.print(f"[red]Request failed\n{error_message}")

    os.remove(agent_zip_path)
