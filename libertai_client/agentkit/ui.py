import asyncio
from collections.abc import Callable
from typing import Any, NoReturn

import typer
from rich.console import Console
from rich.status import Status

console = Console()


def _fail(label: str, error: Exception) -> NoReturn:
    console.print(f"  [red]✘[/red] {label}")
    console.print(f"    [red]{type(error).__name__}: {error or repr(error)}[/red]")
    raise typer.Exit(1)


async def _run_step(
    label: str, fn: Callable[[], Any] | None = None, mock_duration: float = 2.0
) -> Any:
    try:
        with Status(f"{label}...", console=console, spinner="dots"):
            if fn is not None:
                result = await fn()
            else:
                await asyncio.sleep(mock_duration)
                result = None
        console.print(f"  [green]✔[/green] {label}")
        return result
    except Exception as e:
        _fail(label, e)
