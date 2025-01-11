import re
import tomllib

import requests
from poetry.core.constraints.version import Version
from poetry.core.constraints.version.parser import parse_constraint

from libertai_client.interfaces.agent import AgentPythonPackageManager
from libertai_client.utils.system import get_full_path


def __fetch_real_python_versions() -> list[str]:
    response = requests.get(
        "https://api.github.com/repos/python/cpython/tags?per_page=100"
    )
    if response.status_code == 200:
        releases = response.json()
        versions = [str(release["name"]).removeprefix("v") for release in releases]
        exact_versions = [v for v in versions if re.match(r"^\d+\.\d+\.\d+$", v)]
        return exact_versions
    else:
        return []


def detect_python_project_version(
    project_path: str,
    package_manager: AgentPythonPackageManager,
) -> str | None:
    if package_manager == AgentPythonPackageManager.poetry:
        pyproject_path = get_full_path(project_path, "pyproject.toml")
        with open(pyproject_path, "rb") as file:
            pyproject_data = tomllib.load(file)

        # The version might be a range, let's try to find an exact version that is in this range
        version_range = pyproject_data["tool"]["poetry"]["dependencies"]["python"]
        real_python_versions = __fetch_real_python_versions()

        constraint = parse_constraint(version_range)
        for version in real_python_versions:
            if constraint.allows(Version.parse(version)):
                return version

    # Checking common venv folders config
    for venv_folder in ["venv", ".venv"]:
        try:
            venv_config_path = get_full_path(project_path, f"{venv_folder}/pyvenv.cfg")
            with open(venv_config_path, "r") as file:
                for line in file:
                    if line.startswith("version"):
                        return line.split("=")[1].strip()
        except FileNotFoundError:
            pass
    #
    # # Checking if we have a .python-version file, for example created by pyenv
    try:
        version_file_path = get_full_path(project_path, ".python-version")
        with open(version_file_path, "r") as file:
            return file.readline().strip()
    except FileNotFoundError:
        pass

    # TODO: if pyproject, look in pyproject.toml
    # TODO: if pip, look in requirements.txt
    return None
