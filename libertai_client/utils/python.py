import re
import tomllib

import requests
from libertai_utils.interfaces.agent import AgentPythonPackageManager
from poetry.core.constraints.version import Version
from poetry.core.constraints.version.parser import parse_constraint

from libertai_client.utils.system import get_full_path


def validate_python_version(version: str) -> bool:
    # TODO: check if valid docker image
    if re.match(r"^3(?:\.\d+){0,2}$", version):
        return True
    return False


def __fetch_real_python_versions() -> list[str]:
    response = requests.get(
        "https://api.github.com/repos/python/cpython/tags?per_page=100"
    )
    if response.status_code == 200:
        releases = response.json()
        versions = [str(release["name"]).removeprefix("v") for release in releases]
        exact_versions = [v for v in versions if validate_python_version(v)]
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

    # Checking if we have a .python-version file, for example created by pyenv
    try:
        version_file_path = get_full_path(project_path, ".python-version")
        with open(version_file_path, "r") as file:
            return file.readline().strip()
    except FileNotFoundError:
        pass

    # TODO: if pyproject, look in pyproject.toml
    # TODO: if pip, look in requirements.txt
    return None


def detect_python_dependencies_management(
    project_path: str,
) -> AgentPythonPackageManager | None:
    try:
        _poetry_lock_path = get_full_path(project_path, "poetry.lock")
        # Path was found without throwing an error, its poetry
        return AgentPythonPackageManager.poetry
    except FileNotFoundError:
        pass

    try:
        _requirements_path = get_full_path(project_path, "requirements.tx")
        # Path was found without throwing an error, we can use this to install deps
        return AgentPythonPackageManager.requirements
    except FileNotFoundError:
        pass

    try:
        _pyproject_path = get_full_path(project_path, "pyproject.toml")
        # Path was found without throwing an error, and Poetry tested earlier so it should be a standard pyproject
        return AgentPythonPackageManager.pyproject
    except FileNotFoundError:
        pass

    return None
