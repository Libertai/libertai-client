from pydantic import BaseModel


class AgentConfig(BaseModel):
    id: str
    secret: str
