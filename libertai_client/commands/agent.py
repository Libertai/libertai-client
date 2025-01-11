import json
import os
from typing import Annotated

import aiohttp
import rich
import typer
from dotenv import dotenv_values
from libertai_utils.interfaces.agent import UpdateAgentResponse
from rich.console import Console

from libertai_client.config import config
from libertai_client.interfaces.agent import AgentPythonPackageManager, AgentUsageType
from libertai_client.utils.agent import parse_agent_config_env, create_agent_zip
from libertai_client.utils.python import detect_python_project_version
from libertai_client.utils.system import get_full_path
from libertai_client.utils.typer import AsyncTyper

app = AsyncTyper(name="agent", help="Deploy and manage agents")

err_console = Console(stderr=True)


@app.command()
async def deploy(
    path: Annotated[str, typer.Argument(help="Path to the root of your project")] = ".",
    python_version: Annotated[
        str | None, typer.Option(help="Version to deploy with", prompt=False)
    ] = None,
    package_manager: Annotated[
        AgentPythonPackageManager | None,
        typer.Option(
            help="Package manager used to handle dependencies",
            case_sensitive=False,
            prompt=False,
        ),
    ] = None,
    usage_type: Annotated[
        AgentUsageType,
        typer.Option(
            help="How the agent is called", case_sensitive=False, prompt=False
        ),
    ] = AgentUsageType.fastapi,
):
    """
    Deploy or redeploy an agent
    """

    # TODO: allow user to give a custom deployment script URL

    try:
        libertai_env_path = get_full_path(path, ".env.libertai")
        libertai_config = parse_agent_config_env(dotenv_values(libertai_env_path))
    except (FileNotFoundError, EnvironmentError) as error:
        err_console.print(f"[red]{error}")
        raise typer.Exit(1)

    # TODO: try to detect package manager, show detected value and ask user for the confirmation or change
    if package_manager is None:
        package_manager = AgentPythonPackageManager.poetry

    if python_version is None:
        # Trying to find the python version
        detected_python_version = detect_python_project_version(path, package_manager)
        # Confirming the version with the user (or asking if none found)
        python_version = typer.prompt("Python version", default=detected_python_version)

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
