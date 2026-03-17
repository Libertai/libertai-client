import typer

from libertai_client.commands import agent, agentkit

app = typer.Typer(help="Simple CLI to interact with LibertAI products")

app.add_typer(agent.app)
app.add_typer(agentkit.app)
