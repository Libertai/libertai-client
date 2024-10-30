import typer

app = typer.Typer()


@app.command()
def hello_world():
    """
    Says hello
    """
    typer.echo("Hello World!")
