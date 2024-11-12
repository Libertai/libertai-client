import json
from typing import Annotated

import typer
from docker import client  # type: ignore
from docker.models.containers import Container  # type: ignore
from dotenv import dotenv_values
from rich.console import Console
from rich.progress import Progress, TextColumn, SpinnerColumn, TimeElapsedColumn

from libertai_client.config import config
from libertai_client.interfaces.agent import DockerCommand, UpdateAgentResponse
from libertai_client.utils.agent import parse_agent_config_env, get_vm_host_url
from libertai_client.utils.rich import TaskOfTotalColumn, TEXT_PROGRESS_FORMAT
from libertai_client.utils.system import get_full_path

app = typer.Typer(name="agent", help="Deploy and manage agents")

err_console = Console(stderr=True)


@app.command()
def deploy(path: Annotated[str, typer.Option(help="Path to the root of your repository", prompt=True)] = ".",
           code_path: Annotated[
               str, typer.Option(help="Path to the package that contains the code", prompt=True)] = "./src"):
    """
    Deploy or redeploy an agent
    """

    try:
        requirements_path = get_full_path(path, "requirements.txt")
        libertai_env_path = get_full_path(path, ".env.libertai")
        code_path = get_full_path(code_path)
    except FileNotFoundError as error:
        err_console.print(f"[red]{error}")
        raise typer.Exit(1)

    try:
        libertai_config = parse_agent_config_env(dotenv_values(libertai_env_path))
    except EnvironmentError as error:
        err_console.print(f"[red]{error}")
        raise typer.Exit(1)

    commands: list[DockerCommand] = [
        DockerCommand(title="Updating system packages", content="apt-get update"),
        DockerCommand(title="Installing system dependencies",
                      # TODO: make sure we are using the right version of python in docker, and maybe use a venv for safety
                      content="apt-get install python3-pip squashfs-tools curl -y"),
        DockerCommand(title="Installing agent packages",
                      content="pip install -t /opt/packages -r /opt/requirements.txt"),
        DockerCommand(title="Generating agent packages archive",
                      content="mksquashfs /opt/packages /opt/packages.squashfs -noappend"),
        DockerCommand(title="Generating agent code archive",
                      content="mksquashfs /opt/code /opt/code.squashfs -noappend"),
        DockerCommand(title="Uploading to Aleph and creating the agent VM",
                      content=f"""curl --no-progress-meter --fail-with-body -X 'PUT' \
                                    '{config.AGENTS_BACKEND_URL}/agent/{libertai_config.id}' \
                                    -H 'accept: application/json' \
                                    -H 'Content-Type: multipart/form-data' \
                                    -F 'secret="{libertai_config.secret}"' \
                                    -F code=@/opt/code.squashfs \
                                    -F packages=@/opt/packages.squashfs \
                                    2>/dev/null;
                                    """)
    ]

    # Setup
    with Progress(TextColumn(TEXT_PROGRESS_FORMAT),
                  SpinnerColumn(finished_text="✔ ")) as progress:
        setup_task_text = "Starting Docker container"
        task = progress.add_task(f"{setup_task_text}", start=True, total=1)
        docker_client = client.from_env()
        container: Container = docker_client.containers.run("debian:bookworm", platform="linux/amd64", tty=True,
                                                            detach=True, volumes={
                requirements_path: {'bind': '/opt/requirements.txt', 'mode': 'ro'},
                code_path: {'bind': '/opt/code', 'mode': 'ro'}
            })
        progress.update(task, description=f"[green]{setup_task_text}", advance=1)

    agent_result: str | None = None
    error_message: str | None = None

    with Progress(TaskOfTotalColumn(len(commands)), TextColumn(TEXT_PROGRESS_FORMAT),
                  SpinnerColumn(finished_text="✔ "),
                  TimeElapsedColumn()) as progress:
        for command in commands:
            task = progress.add_task(f"{command.title}", start=True, total=1)
            result = container.exec_run(f'/bin/bash -c "{command.content}"')

            if result.exit_code != 0:
                command_output = result.output.decode().strip('\n')
                error_message = f"\n[red]Docker command error: '{command_output}'"
                break

            if command.title == "Uploading to Aleph and creating the agent VM":
                agent_result = result.output.decode()
            progress.update(task, description=f"[green]{command.title}", advance=1)
            progress.stop_task(task)

    if error_message is not None:
        err_console.print(error_message)

    # Cleanup
    with Progress(TextColumn(TEXT_PROGRESS_FORMAT),
                  SpinnerColumn(finished_text="✔ ")) as progress:
        stop_task_text = "Stopping and removing container"
        task = progress.add_task(f"{stop_task_text}", start=True, total=1)
        container.stop()
        container.remove()
        progress.update(task, description=f"[green]{stop_task_text}", advance=1)

    if agent_result is not None:
        agent_data = UpdateAgentResponse(**json.loads(agent_result))
        print(f"Agent successfully deployed on {get_vm_host_url(agent_data.vm_hash)}")
