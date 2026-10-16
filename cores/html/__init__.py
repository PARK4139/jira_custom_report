"""Packaged HTML, CSS, and JavaScript resources."""
from functools import cache
from importlib.resources import files
import hashlib


@cache
def read_asset(name: str) -> str:
    """Read a bundled asset by its internal filename."""
    if "/" in name or "\\" in name or name.startswith("."):
        raise ValueError("Expected an HTML asset filename.")
    return files(__package__).joinpath(name).read_text(encoding="utf-8")


def asset_revision() -> str:
    """Return a digest of source assets so development pages can detect edits."""
    root = files(__package__)
    digest = hashlib.sha256()
    for asset in sorted((item for item in root.iterdir() if item.name.endswith((".html", ".css", ".js"))), key=lambda item: item.name):
        digest.update(asset.name.encode("utf-8"))
        digest.update(asset.read_bytes())
    return digest.hexdigest()
