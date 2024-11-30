import os
import zipfile
from typing import Annotated

import aiohttp
import pathspec
import typer
from dotenv import dotenv_values
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
    with open(get_full_path(src_dir, ".gitignore"), 'r') as gitignore_file:
        gitignore_patterns = gitignore_file.read()
    spec = pathspec.PathSpec.from_lines('gitwildmatch', gitignore_patterns.splitlines() + AGENT_ZIP_BLACKLIST)

    with zipfile.ZipFile(zip_name, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, _, files in os.walk(src_dir):
            for file in files:
                file_path = os.path.join(root, file)
                relative_path = os.path.relpath(file_path, src_dir)

                # Check if the file matches any .gitignore pattern
                if not spec.match_file(relative_path) or relative_path in AGENT_ZIP_WHITELIST:
                    zipf.write(file_path, arcname=relative_path)


@app.command()
async def deploy(path: Annotated[str, typer.Option(help="Path to the root of your repository", prompt=True)] = ".",
                 python_version: Annotated[str, typer.Option(help="Version to deploy with", prompt=True)] = "3.11"):
    """
    Deploy or redeploy an agent
    """

    try:
        libertai_env_path = get_full_path(path, ".env.libertai")
        libertai_config = parse_agent_config_env(dotenv_values(libertai_env_path))
    except (FileNotFoundError, EnvironmentError) as error:
        err_console.print(f"[red]{error}")
        raise typer.Exit(1)

    create_agent_zip(path, "/tmp/libertai-agent.zip")

    data = aiohttp.FormData()
    data.add_field('secret', libertai_config.secret)
    data.add_field('python_version', python_version)
    data.add_field('package_manager', "poetry")  # TODO: detect/ask user
    data.add_field('code', open('/tmp/libertai-agent.zip', 'rb'), filename='libertai-agent.zip')

    async with aiohttp.ClientSession() as session:
        async with session.put(f"{config.AGENTS_BACKEND_URL}/agent/{libertai_config.id}",
                               headers={'accept': 'application/json'},
                               data=data) as response:
            if response.status == 200:
                print("Request succeeded:", await response.text())
            else:
                print(f"Request failed: {response.status}")
                print(await response.text())

    os.remove("/tmp/libertai-agent.zip")

    # with Progress(TextColumn(TEXT_PROGRESS_FORMAT),
    #               SpinnerColumn(finished_text="✔ ")) as progress:
    #     setup_task_text = "Starting Docker container"
    #     task = progress.add_task(f"{setup_task_text}", start=True, total=1)
    #     docker_client = client.from_env()
    #     container: Container = docker_client.containers.run("debian:bookworm", platform="linux/amd64", tty=True,
    #                                                         detach=True, volumes={
    #             requirements_path: {'bind': '/opt/requirements.txt', 'mode': 'ro'},
    #             code_path: {'bind': '/opt/code', 'mode': 'ro'}
    #         })
    #     progress.update(task, description=f"[green]{setup_task_text}", advance=1)
    #
    # agent_result: str | None = None
    # error_message: str | None = None
    #
    # with Progress(TaskOfTotalColumn(len(commands)), TextColumn(TEXT_PROGRESS_FORMAT),
    #               SpinnerColumn(finished_text="✔ "),
    #               TimeElapsedColumn()) as progress:
    #     for command in commands:
    #         task = progress.add_task(f"{command.title}", start=True, total=1)
    #         result = container.exec_run(f'/bin/bash -c "{command.content}"')
    #
    #         if result.exit_code != 0:
    #             command_output = result.output.decode().strip('\n')
    #             error_message = f"\n[red]Docker command error: '{command_output}'"
    #             break
    #
    #         if command.id == "call-backend":
    #             agent_result = result.output.decode()
    #         progress.update(task, description=f"[green]{command.title}", advance=1)
    #         progress.stop_task(task)
    #
    # if error_message is not None:
    #     err_console.print(error_message)
    #
    # # Cleanup
    # with Progress(TextColumn(TEXT_PROGRESS_FORMAT),
    #               SpinnerColumn(finished_text="✔ ")) as progress:
    #     stop_task_text = "Stopping and removing container"
    #     task = progress.add_task(f"{stop_task_text}", start=True, total=1)
    #     container.stop()
    #     container.remove()
    #     progress.update(task, description=f"[green]{stop_task_text}", advance=1)
    #
    # if agent_result is not None:
    #     agent_data = UpdateAgentResponse(**json.loads(agent_result))
    #     print(f"Agent successfully deployed on {get_vm_url(agent_data.vm_hash)}")
    # else:
    #     typer.Exit(1)
