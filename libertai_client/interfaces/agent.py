from pydantic import BaseModel


class UpdateAgentResponse(BaseModel):
    vm_hash: str


class AgentConfig(BaseModel):
    id: str
    secret: str
