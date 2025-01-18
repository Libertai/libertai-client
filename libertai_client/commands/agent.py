import json
import os
from typing import Annotated

import aiohttp
import questionary
import rich
import typer
from dotenv import dotenv_values
from libertai_utils.interfaces.agent import UpdateAgentResponse
from rich.console import Console

from libertai_client.config import config
from libertai_client.interfaces.agent import AgentPythonPackageManager, AgentUsageType
from libertai_client.utils.agent import parse_agent_config_env, create_agent_zip
from libertai_client.utils.python import (
    detect_python_project_version,
    detect_python_dependencies_management,
    validate_python_version,
)
from libertai_client.utils.system import get_full_path
from libertai_client.utils.typer import AsyncTyper

app = AsyncTyper(name="agent", help="Deploy and manage agents")

err_console = Console(stderr=True)

dependencies_management_choices: list[questionary.Choice] = [
    questionary.Choice(
        title="poetry",
        value=AgentPythonPackageManager.poetry,
        description="poetry-style pyproject.toml and poetry.lock",
    ),
    questionary.Choice(
        title="requirements.txt",
        value=AgentPythonPackageManager.requirements,
        description="Any management tool that outputs a requirements.txt file (pip, pip-tools...)",
    ),
    questionary.Choice(
        title="pyproject.toml",
        value=AgentPythonPackageManager.pyproject,
        description="Any tool respecting the standard PEP 621 pyproject.toml (hatch, modern usage of setuptools...)",
    ),
]

usage_type_choices: list[questionary.Choice] = [
    questionary.Choice(
        title="fastapi",
        value=AgentUsageType.fastapi,
        description="API-exposed agent",
    ),
    questionary.Choice(
        title="python",
        value=AgentUsageType.python,
        description="Agent called with Python code",
    ),
]


@app.command()
async def deploy(
    path: Annotated[str, typer.Argument(help="Path to the root of your project")] = ".",
    python_version: Annotated[
        str | None, typer.Option(help="Version to deploy with", prompt=False)
    ] = None,
    dependencies_management: Annotated[
        AgentPythonPackageManager | None,
        typer.Option(
            help="Package manager used to handle dependencies",
            case_sensitive=False,
            prompt=False,
        ),
    ] = None,
    usage_type: Annotated[
        AgentUsageType | None,
        typer.Option(
            help="How the agent is called", case_sensitive=False, prompt=False
        ),
    ] = None,
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

    if dependencies_management is None:
        # Trying to find the way dependencies are managed
        detected_dependencies_management = detect_python_dependencies_management(path)
        # Confirming with the user (or asking if none found)
        dependencies_management = await questionary.select(
            "Dependencies management",
            choices=dependencies_management_choices,
            default=next(
                (
                    choice
                    for choice in dependencies_management_choices
                    if detected_dependencies_management is not None
                    and choice.value == detected_dependencies_management.value
                ),
                None,
            ),
            show_description=True,
        ).ask_async()
        if dependencies_management is None:
            err_console.print(
                "[red]You must select the way Python dependencies are managed."
            )
            raise typer.Exit(1)

    if python_version is None:
        # Trying to find the python version
        detected_python_version = detect_python_project_version(
            path, dependencies_management
        )
        # Confirming the version with the user (or asking if none found)
        python_version = await questionary.text(
            "Python version",
            default=detected_python_version
            if detected_python_version is not None
            else "",
            validate=validate_python_version,
        ).ask_async()

    if usage_type is None:
        usage_type = await questionary.select(
            "Usage type",
            choices=usage_type_choices,
            default=None,
            show_description=True,
        ).ask_async()

    agent_zip_path = "/tmp/libertai-agent.zip"
    create_agent_zip(path, agent_zip_path)

    data = aiohttp.FormData()
    data.add_field("secret", libertai_config.secret)
    data.add_field("python_version", python_version)
    data.add_field("package_manager", dependencies_management.value)
    data.add_field("usage_type", usage_type.value)
    data.add_field("code", open(agent_zip_path, "rb"), filename="libertai-agent.zip")

    async with aiohttp.ClientSession() as session:
        async with session.put(
            f"{config.AGENTS_BACKEND_URL}/agent/{libertai_config.id}",
            headers={"accept": "application/json"},
            data=data,
        ) as response:
            if response.status == 200:
                response_data = UpdateAgentResponse(**json.loads(await response.text()))
                success_text = (
                    f"Agent successfully deployed on http://[{response_data.instance_ip}]:8000/docs"
                    if usage_type == AgentUsageType.fastapi
                    else f"Agent successfully deployed on instance {response_data.instance_ip}"
                )
                rich.print(f"[green]{success_text}")
            else:
                error_message = await response.json()
                err_console.print(
                    f"[red]Request failed: {error_message.get("detail", "An unknown error happened.")}"
                )

    os.remove(agent_zip_path)
