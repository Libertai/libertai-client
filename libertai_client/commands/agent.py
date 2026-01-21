import os
from http import HTTPStatus
from pathlib import Path
from typing import Annotated

import aiohttp
import paramiko
import rich
import typer
from dotenv import dotenv_values
from paramiko import AuthenticationException
from rich.console import Console

from libertai_client.config import config
from libertai_client.interfaces.agent import GetAgentResponse
from libertai_client.utils.agent import parse_agent_config_env, create_agent_zip
from libertai_client.utils.system import (
    get_full_path,
)
from libertai_client.utils.typer import AsyncTyper, validate_optional_file_path_argument

app = AsyncTyper(name="agent", help="Deploy and manage agents")

err_console = Console(stderr=True)


@app.command()
async def deploy(
    path: Annotated[str, typer.Argument(help="Path to the root of your project")] = ".",
    ssh_key_filename: Annotated[
        Path | None,
        typer.Option(
            "--ssh-key",
            help="Path to SSH private key file",
            case_sensitive=False,
            prompt=False,
            callback=validate_optional_file_path_argument,
        ),
    ] = None,
):
    """
    Deploy or redeploy an agent
    """

    try:
        libertai_env_path = get_full_path(path, ".env")
        libertai_config = parse_agent_config_env(dotenv_values(libertai_env_path))
    except (FileNotFoundError, EnvironmentError) as error:
        err_console.print(f"[red]{error}")
        raise typer.Exit(1)

    agent_zip_path = "/tmp/libertai-agent.zip"
    create_agent_zip(path, agent_zip_path)

    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{config.AGENTS_BACKEND_URL}/agents/{libertai_config.agent_id}",
            headers={"accept": "application/json"},
        ) as response:
            if response.status != HTTPStatus.OK:
                try:
                    error_message = (await response.json()).get(
                        "detail", "An unknown error occurred."
                    )
                except aiohttp.ContentTypeError:
                    error_message = await response.text()
                err_console.print(
                    f"[red]Fetching agent details failed: {error_message}"
                )
                raise typer.Exit(1)

            agent_data = GetAgentResponse(**(await response.json()))
            if agent_data.instance_hash is None:
                err_console.print("[red]Agent has no instance linked to it.")
                raise typer.Exit(1)
            elif agent_data.subscription_status == "inactive":
                err_console.print("[red]Agent subscription is inactive.")
                raise typer.Exit(1)
            elif agent_data.instance_ip is None:
                err_console.print(
                    "[red]Agent instance doesn't seem to be allocated yet, wait a few minutes and try again."
                )
                raise typer.Exit(1)
            else:
                rich.print(f"[green]Agent '{agent_data.name}' found, deploying...")

            # Create a Paramiko SSH client
            ssh_client = paramiko.SSHClient()
            ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            try:
                # Connect to the server
                ssh_client.connect(
                    hostname=agent_data.instance_ip,
                    username="root",
                    key_filename=str(ssh_key_filename) if ssh_key_filename else None,
                )
            except AuthenticationException:
                err_console.print(
                    "[red]SSH authentication failed, please use the --ssh-key option to specify your private key file if necessary."
                )
                raise typer.Exit(1)

            # Send the zip with the code
            sftp = ssh_client.open_sftp()
            remote_path = "/tmp/libertai-agent.zip"
            sftp.put(agent_zip_path, remote_path)
            sftp.close()

            script_path = "/tmp/deploy-agent.sh"

            # Execute the command
            _stdin, _stdout, stderr = ssh_client.exec_command(
                f"wget {config.DEPLOY_SCRIPT_URL} -O {script_path} -q --no-cache && chmod +x {script_path} && {script_path}"
            )
            # Waiting for the command to complete to get error logs
            stderr.channel.recv_exit_status()

            # Close the connection
            ssh_client.close()

            error_log = stderr.read()

            if len(error_log) > 0:
                # Errors occurred
                err_console.print(f"[red]Error log:\n{error_log.decode()}")
                warning_text = "Some errors occurred during the deployment, please check the logs above and make sure your agent is running correctly. If not, try to redeploy it and contact the LibertAI team if the issue persists."
                rich.print(f"[yellow]{warning_text}")
            else:
                success_text = f"Agent successfully deployed on the instance (IPv6: {agent_data.instance_ip})"
                rich.print(f"[green]{success_text}")

    os.remove(agent_zip_path)
