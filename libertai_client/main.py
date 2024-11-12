import typer

from libertai_client.commands import agent

app = typer.Typer(help="Simple CLI to interact with LibertAI products")

app.add_typer(agent.app)
