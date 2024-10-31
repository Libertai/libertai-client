import os


def __validate_path(path: str, with_file: bool = False) -> str:
    is_valid_path = os.path.exists(path)

    if not is_valid_path:
        raise FileNotFoundError(f"{'File' if with_file else 'Folder'} '{path}' doesn't exist.")

    return path


def get_full_path(folder_path: str, file: str | None = None) -> str:
    if file is None:
        path = os.path.abspath(folder_path)
        return __validate_path(path, with_file=False)

    path = os.path.abspath(f'{folder_path}/{file}')
    return __validate_path(path, with_file=True)
