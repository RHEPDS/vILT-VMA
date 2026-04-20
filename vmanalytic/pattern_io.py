"""Shared helpers for line-based pattern files."""


def load_line_set(path: str) -> set[str]:
    """Load non-empty lines from a file as a set."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return {line.strip() for line in f if line.strip()}
    except FileNotFoundError:
        return set()


def append_unique_line(path: str, line: str) -> bool:
    """
    Append a line if it is not already present.
    Returns True if appended, False if duplicate.
    """
    existing = load_line_set(path)
    if line in existing:
        return False
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    return True
