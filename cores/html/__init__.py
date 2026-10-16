"""Packaged HTML, CSS, and JavaScript resources."""
from functools import cache
from importlib.resources import files


@cache
def read_asset(name: str) -> str:
    """Read a bundled asset by its internal filename."""
    if "/" in name or "\\" in name or name.startswith("."):
        raise ValueError("Expected an HTML asset filename.")
    return files(__package__).joinpath(name).read_text(encoding="utf-8")
