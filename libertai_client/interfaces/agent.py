from pydantic import BaseModel


class AgentConfig(BaseModel):
    id: str
    secret: str

class PublicAgentData(BaseModel):
    id: str
    subscription_id: str
    instance_hash: str
    last_update: int


class Agent(PublicAgentData):
    encrypted_secret: str
    encrypted_ssh_key: str
    tags: list[str]


class FetchedAgent(Agent):
    post_hash: str
