import os
import re
from pathlib import Path


def __validate_path(path: str, with_file: bool = False) -> str:
    is_valid_path = os.path.exists(path)

    if not is_valid_path:
        raise FileNotFoundError(
            f"{'File' if with_file else 'Folder'} '{path}' doesn't exist."
        )

    return path


def get_full_path(folder_path: str, file: str | None = None) -> str:
    if file is None:
        path = os.path.abspath(folder_path)
        return __validate_path(path, with_file=False)

    path = os.path.abspath(f"{folder_path}/{file}")
    return __validate_path(path, with_file=True)


def str_to_path(path: str) -> Path:
    return Path(path).expanduser()


def is_str_valid_file_path(path: str | None) -> bool:
    if path is None:
        return False
    try:
        file_path = str_to_path(path)
    except RuntimeError:
        # Potentially failed to expand the ~
        return False

    if not file_path.exists() or not file_path.is_file():
        return False
    return True


def is_valid_ssh_public_key(key: str) -> bool:
    # Define regex pattern for public SSH key
    pattern = r"^ssh-(rsa|ed25519|dss) [A-Za-z0-9+/=]+( [^@]+@[^ ]+)?$"

    if re.match(pattern, key.strip()):
        return True
    return False
