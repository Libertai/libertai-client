from enum import Enum

from pydantic import BaseModel


class AgentConfig(BaseModel):
    id: str
    secret: str


class AgentPythonPackageManager(str, Enum):
    poetry = "poetry"
    requirements = "requirements"
    pyproject = "pyproject"


class AgentUsageType(str, Enum):
    fastapi = "fastapi"
    python = "python"
