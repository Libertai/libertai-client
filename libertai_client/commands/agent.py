import json
import os
import io
from pathlib import Path
from typing import Annotated
import paramiko
import aiohttp
import questionary
import rich
import typer
from aiohttp import ContentTypeError
from dotenv import dotenv_values
from fastapi import HTTPException
from http import HTTPStatus
from aleph.sdk import AuthenticatedAlephHttpClient
from aleph.sdk.chains.ethereum import ETHAccount
from libertai_utils.interfaces.agent import (
    AgentPythonPackageManager,
    AgentUsageType,
    AddSSHKeyAgentBody,
    AddSSHKeyAgentResponse,
    UpdateAgentResponse,
)
from libertai_client.interfaces.agent import Agent
from rich.console import Console
import time

from libertai_client.config import config
from libertai_client.interfaces.agent import FetchedAgent
from libertai_client.utils.agent import parse_agent_config_env, create_agent_zip
from libertai_client.utils.python import (
    detect_python_project_version,
    detect_python_dependencies_management,
    validate_python_version,
)
from libertai_client.utils.system import (
    get_full_path,
    is_str_valid_file_path,
    str_to_path,
    is_valid_ssh_public_key,
)
from libertai_client.utils.typer import AsyncTyper, validate_optional_file_path_argument

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
    deploy_script_url: Annotated[
        str | None,
        typer.Option(
            help="Optional custom deployment script URL",
            case_sensitive=False,
            prompt=False,
        ),
    ] = None,
    shh_private_key_filepath: Annotated[
        str | None,
        typer.Option(
            help="Filepath of of the file containing the private ssh key",
            case_sensitive=False,
            prompt=False,
        ),
    ] = None,
    format: Annotated[
        bool,
        typer.Option("--json", help="Set the output format to JSON"),
    ] = False,
):
    """
    Deploy or redeploy an agent
    """

    try:
        libertai_env_path = get_full_path(path, ".env.libertai")
        libertai_config = parse_agent_config_env(dotenv_values(libertai_env_path))
    except (FileNotFoundError, EnvironmentError) as error:
        err_console.print(f"[red]{error}")
        raise typer.Exit(1)

    if shh_private_key_filepath is None:
        err_console.print("[red]--shh-private-key-filepath flag is mandatory")
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

    if python_version is not None:
        # Checking if the given Python version is in the right format
        if not validate_python_version(python_version):
            # Reset it to use the auto-detect and question with validation
            python_version = None

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
        if python_version is None:
            # User interrupted the question
            raise typer.Exit(1)

    if usage_type is None:
        usage_type = await questionary.select(
            "Usage type",
            choices=usage_type_choices,
            default=None,
            show_description=True,
        ).ask_async()
        if usage_type is None:
            # User interrupted the question
            raise typer.Exit(1)

    agent_zip_path = "/tmp/libertai-agent.zip"
    create_agent_zip(path, agent_zip_path)

    agent = FetchedAgent(
        id="9c0a5d82-25fd-44b8-9c60-2966a7b3bbcb",
        subscription_id="37ff36f1-0195-4df3-81c5-f45c4d7ee1e7",
        instance_hash="cb86c6678a0984a66f8d0b066ccfb7b1e9364967809df47c9adc0efa51aa76b9",
        last_update=1746546443,
        encrypted_secret="",
        encrypted_ssh_key="",
        tags=[],
        post_hash="65dcf867f546e7d44b92dd973ad5922fd3818814be341ea0521c49633a429512"
    )

    f = open(shh_private_key_filepath)
    ssh_private_key = f.read()
    f.close()
    hostname = "[2a01:240:ad00:2501:3:8668:77de:f9b1]"

    ssh_client = paramiko.SSHClient()
    ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    rsa_key = paramiko.RSAKey(file_obj=io.StringIO(ssh_private_key))

    zipFile = open(agent_zip_path, "rb")
    content = zipFile.read()
    zipFile.close()
    ssh_client.connect(hostname=hostname, username="root", pkey=rsa_key)


    sftp = ssh_client.open_sftp()
    remote_path = "/tmp/libertai-agent.zip"
    sftp.putfo(io.BytesIO(content), remote_path)
    sftp.close()

    script_path = "/tmp/deploy-agent.sh"
    
    _stdin, _stdout, stderr = ssh_client.exec_command(
        f"wget {deploy_script_url} -O {script_path} -q --no-cache && chmod +x {script_path} && {script_path} {python_version} {dependencies_management} {usage_type}"
    )

    stderr.channel.recv_exit_status()
    
    ssh_client.close()
    
    aleph_account = ETHAccount(config.ALEPH_SENDER_SK)
    
    async with AuthenticatedAlephHttpClient(
        account=aleph_account, api_server=config.ALEPH_API_URL
    ) as client:
        # Updating the related POST message
        await client.create_post(
            address=config.ALEPH_OWNER,
            post_content=Agent(
                **agent.dict(exclude={"last_update"}),
                last_update=int(time.time()),
            ),
            post_type="amend",
            ref=agent.post_hash,
            channel=config.ALEPH_CHANNEL,
        )
    agent_response = UpdateAgentResponse(instance_ip=hostname, error_log=stderr.read())
    print(agent_response)

    # async with aiohttp.ClientSession() as session:
    #     async with session.put(
    #         f"{config.AGENTS_BACKEND_URL}/agent/{libertai_config.id}",
    #         headers={"accept": "application/json"},
    #         data=data,
    #     ) as response:
    #         if response.status == 200:
    #             response_data = UpdateAgentResponse(**json.loads(await response.text()))
    #             if len(response_data.error_log) > 0:
    #                 # Errors occurred
    #                 if format:
    #                     json_object = {"success": False, "message": response_data.error_log}
    #                     json_formatted_str = json.dumps(json_object, indent=2)
    #                     rich.print(json_formatted_str)
    #                 else:
    #                     err_console.print(f"[red]Error log:\n{response_data.error_log}")
    #                     warning_text = "Some errors occurred during the deployment, please check the logs above and make sure your agent is running correctly. If not, try to redeploy it and contact the LibertAI team if the issue persists."
    #                     rich.print(f"[yellow]{warning_text}")
    #                 raise typer.Exit(1)
    #             else:
    #                 url = f"http://[{response_data.instance_ip}]:8000"
    #                 success_text = f"Agent successfully deployed on {url}/docs"
                    
    #                 if format:
    #                     json_object = {"success": True, "message": success_text, "url": url}
    #                     json_formatted_str = json.dumps(json_object, indent=2)
    #                     rich.print(json_formatted_str)
    #                 else:
    #                     success_text += (
    #                         ""
    #                         if usage_type == AgentUsageType.fastapi
    #                         else f"Agent successfully deployed on instance {response_data.instance_ip}"
    #                     )
    #                     rich.print(f"[green]{success_text}")
    #         else:
    #             try:
    #                 error_message = (await response.json()).get(
    #                     "detail", "An unknown error happened."
    #                 )
    #             except ContentTypeError:
    #                 error_message = await response.text()
    #             if format:
    #                 json_object = {"success": False, "message": f"Request failed: {error_message}"}
    #                 json_formatted_str = json.dumps(json_object, indent=2)
    #                 rich.print(json_formatted_str)
    #             else:
    #                 err_console.print(f"[red]Request failed: {error_message}")

    os.remove(agent_zip_path)


@app.command()
async def add_ssh_key(
    path: Annotated[str, typer.Argument(help="Path to the root of your project")] = ".",
    ssh_public_key_file: Annotated[
        Path | None,
        typer.Option(
            help="Path to the public key file",
            case_sensitive=False,
            prompt=False,
            callback=validate_optional_file_path_argument,
        ),
    ] = None,
    format: Annotated[
        bool,
        typer.Option("--json", help="Set the output format to JSON"),
    ] = False,
):
    """
    Add an SSH key to an agent instance
    """

    try:
        libertai_env_path = get_full_path(path, ".env.libertai")
        libertai_config = parse_agent_config_env(dotenv_values(libertai_env_path))
    except (FileNotFoundError, EnvironmentError) as error:
        err_console.print(f"[red]{error}")
        raise typer.Exit(1)

    if ssh_public_key_file is None:
        ssh_public_key_file = str_to_path(
            await questionary.text(
                "SSH public key file path",
                validate=is_str_valid_file_path,
            ).ask_async()
        )
        if ssh_public_key_file is None:
            # User interrupted the question
            raise typer.Exit(1)

    ssh_public_key = ssh_public_key_file.read_text(encoding="utf-8").strip()
    if not is_valid_ssh_public_key(ssh_public_key):
        err_console.print("[red]Invalid SSH key")
        raise typer.Exit(1)

    data = AddSSHKeyAgentBody(secret=libertai_config.secret, ssh_key=ssh_public_key)

    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{config.AGENTS_BACKEND_URL}/agent/{libertai_config.id}/ssh-key",
            headers={"accept": "application/json"},
            json=json.loads(data.json()),
        ) as response:
            if response.status == 200:
                response_data = AddSSHKeyAgentResponse(
                    **json.loads(await response.text())
                )
                if len(response_data.error_log) > 0:
                    # Errors occurred
                    warning_text = "Some errors occurred during the addition of the SSH key, please check the logs above."
                    if format:
                        json_object = {"success": False, "message": response_data.error_log, "error_log": response_data.error_log}
                        json_formatted_str = json.dumps(json_object, indent=2)
                        rich.print(json_formatted_str)
                    else:
                        err_console.print(f"[red]Error log:\n{response_data.error_log}")
                        rich.print(f"[yellow]{warning_text}")
                    raise typer.Exit(1)
                else:
                    if format:
                        json_object = {"success": True, "message": "SSH key successfully added"}
                        json_formatted_str = json.dumps(json_object, indent=2)
                        rich.print(json_formatted_str)
                    else:
                        rich.print("[green]SSH key successfully added")
            else:
                try:
                    error_message = (await response.json()).get(
                        "detail", "An unknown error happened."
                    )
                except ContentTypeError:
                    error_message = await response.text()
                if format:
                    json_object = {"success": False, "message": f"Request failed: {error_message}"}
                    json_formatted_str = json.dumps(json_object, indent=2)
                    rich.print(json_formatted_str)
                else:
                    err_console.print(f"[red]Request failed: {error_message}")
