from rich.progress import ProgressColumn, Task
from rich.style import Style
from rich.text import Text

TEXT_PROGRESS_FORMAT = "[progress.description]{task.description}"


class TaskOfTotalColumn(ProgressColumn):
    def __init__(self, total: int):
        self.separator = "/"
        self.total = total
        super().__init__()

    def render(self, task: "Task") -> Text:
        """Show current/total."""
        completed = task.id + 1
        total_width = len(str(self.total))
        return Text(
            f"[{completed:{total_width}d}{self.separator}{self.total}]",
            Style(color="green" if task.completed else None),
        )
