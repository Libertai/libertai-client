import asyncio
import inspect
from functools import wraps, partial
from pathlib import Path

from typer import Typer, BadParameter


class AsyncTyper(Typer):
    @staticmethod
    def maybe_run_async(decorator, f):
        if inspect.iscoroutinefunction(f):

            @wraps(f)
            def runner(*args, **kwargs):
                return asyncio.run(f(*args, **kwargs))

            decorator(runner)
        else:
            decorator(f)
        return f

    def callback(self, *args, **kwargs):
        decorator = super().callback(*args, **kwargs)
        return partial(self.maybe_run_async, decorator)

    def command(self, *args, **kwargs):
        decorator = super().command(*args, **kwargs)
        return partial(self.maybe_run_async, decorator)


def validate_optional_file_path_argument(file_path: Path | None) -> Path | None:
    if file_path is None:
        return file_path
    if not file_path.exists():
        raise BadParameter(f"File '{file_path}' does not exist.")
    if not file_path.is_file():
        raise BadParameter(f"'{file_path}' is not a valid file.")
    return file_path
