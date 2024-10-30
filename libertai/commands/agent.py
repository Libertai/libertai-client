import os
from typing import Annotated

import typer
from docker import client  # type: ignore
from docker.models.containers import Container  # type: ignore
from rich.progress import Progress, TextColumn, SpinnerColumn, TimeElapsedColumn

from libertai.interfaces.agent import DockerCommand
from libertai.utils.rich import TaskOfTotalColumn

app = typer.Typer(name="agent", help="Deploy and manage agents")


@app.command()
def deploy(path: Annotated[str, typer.Option(help="Path to the root of your repository", prompt=True)] = ".",
           code_path: Annotated[
               str, typer.Option(help="Path to the package that contains the code", prompt=True)] = "./test"):
    """
    Deploy or redeploy an agent
    """

    commands: list[DockerCommand] = [DockerCommand(title="Updating system packages", content="apt-get update"),
                                     DockerCommand(title="Installing system dependencies",
                                                   content="apt-get install python3-pip squashfs-tools curl jq -y"),
                                     DockerCommand(title="Installing agent packages",
                                                   content="pip install -t /opt/packages -r /opt/requirements.txt"),
                                     DockerCommand(title="Generating agent packages archive",
                                                   content="mksquashfs /opt/packages /opt/packages.squashfs -noappend"),
                                     DockerCommand(title="Generating agent code archive",
                                                   content="mksquashfs /opt/code /opt/code.squashfs -noappend")]

    docker_client = client.from_env()
    container: Container = docker_client.containers.run("debian:bookworm", platform="linux/amd64", tty=True,
                                                        detach=True, volumes={
            os.path.abspath(f'{path}/requirements.txt'): {'bind': '/opt/requirements.txt', 'mode': 'ro'},
            os.path.abspath(f'{code_path}'): {'bind': '/opt/code', 'mode': 'ro'}
        })

    with Progress(TaskOfTotalColumn(len(commands)), TextColumn("[progress.description]{task.description}"),
                  SpinnerColumn(finished_text="✔ "),
                  TimeElapsedColumn()) as progress:
        for command in commands:
            task = progress.add_task(f"{command.title}", start=True, total=1)
            container.exec_run(f'/bin/bash -c "{command.content}"')
            progress.update(task, description=f"[green]{command.title}", advance=1)
            progress.stop_task(task)

    # Cleanup
    with Progress(TextColumn("[progress.description]{task.description}"),
                  SpinnerColumn(finished_text="✔ ")) as progress:
        stop_task_text = "Stopping and removing container"
        task = progress.add_task(f"{stop_task_text}", start=True, total=1)
        container.stop()
        container.remove()
        progress.update(task, description=f"[green]{stop_task_text}", advance=1)

# docker run --rm -t --platform linux/amd64 \
#   -v ./requirements.txt:/opt/requirements.txt:ro \
#   -v $CODE_PATH:/opt/code:ro \
#   debian:bookworm /bin/bash \
#   -c "
#   apt-get update;
#   apt-get install python3-pip squashfs-tools curl jq -y;
#
#   pip install -t /opt/packages -r /opt/requirements.txt;
#
#   mksquashfs /opt/packages /opt/packages.squashfs -noappend;
#   mksquashfs /opt/code /opt/code.squashfs -noappend;
#
#   vm_hash=\$(curl -X 'POST' \
#   'https://98c3-58-142-26-96.ngrok-free.app/test' \
#   -H 'accept: application/json' \
#   -H 'Content-Type: multipart/form-data' \
#   -F code=@/opt/code.squashfs \
#   -F packages=@/opt/packages.squashfs | jq -r '.vm_hash');
#
#   echo \"Deployed on https://aleph-crn.rezar.fr/vm/\${vm_hash}\";"
