from pydantic import BaseModel


class DockerCommand(BaseModel):
    title: str
    content: str


class UpdateAgentResponse(BaseModel):
    vm_hash: str


class AgentConfig(BaseModel):
    id: str
    secret: str
