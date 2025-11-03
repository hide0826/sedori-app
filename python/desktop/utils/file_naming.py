from pathlib import Path

def resolve_unique_path(path: Path) -> Path:
    """
    指定パスが既に存在する場合、"name(1).ext", "name(2).ext" のように
    連番を付けて存在しないパスを返す。
    """
    if not path.exists():
        return path

    stem = path.stem
    suffix = path.suffix
    parent = path.parent

    counter = 1
    while True:
        candidate = parent / f"{stem}({counter}){suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


