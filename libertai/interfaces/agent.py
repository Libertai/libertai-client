from pydantic import BaseModel


class DockerCommand(BaseModel):
    title: str
    content: str
