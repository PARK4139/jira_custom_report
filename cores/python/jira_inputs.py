"""Remember dashboard inputs (filters, language, theme) in a git-ignored local file.

The browser keeps the same values in localStorage; this copy lets them survive a server restart even when the
dashboard comes back on a different port, which gives the browser a new, empty localStorage.
No credentials, URLs, or Jira data are stored here.
"""
import json
import os
import re
import tempfile

import jira_paths
from jira_periods import PERIODS

F_INPUTS = jira_paths.D_LOCAL / "inputs.json"
MAX_VALUE = 20000
MAX_ITEMS = 100


def _text(value, limit=200) -> bool:
    return isinstance(value, str) and len(value) <= limit and not any(ord(c) < 32 or ord(c) == 127 for c in value)


def _list_of_names(value: str) -> bool:
    try:
        items = json.loads(value)
    except ValueError:
        return False
    if not isinstance(items, list) or len(items) > MAX_ITEMS:
        return False
    for item in items:
        if isinstance(item, dict):
            if set(item) != {"value", "label"} or not _text(item["value"]) or not _text(item["label"]):
                return False
        elif not _text(item):
            return False
    return True


VALIDATORS = {
    "year": lambda value: re.fullmatch(r"\d{4}", value) is not None,
    "period": lambda value: value in PERIODS,
    "mode": lambda value: value in ("cumulative", "periodic"),
    "locale": lambda value: value in ("ko", "en"),
    "theme": lambda value: value in ("light", "dark"),
    "projects": _list_of_names,
    "reporters": _list_of_names,
}


def valid_inputs(values) -> bool:
    return (isinstance(values, dict) and set(values) <= set(VALIDATORS)
            and all(isinstance(value, str) and len(value) <= MAX_VALUE and VALIDATORS[key](value)
                    for key, value in values.items()))


def load_inputs() -> dict:
    """Return the saved inputs, or {} when the file is missing or no longer valid."""
    try:
        values = json.loads(F_INPUTS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(values, dict):
        return {}
    # Keep every value that is still valid: a saved period that no longer exists must not discard the other inputs.
    return {key: value for key, value in values.items() if key in VALIDATORS and isinstance(value, str)
            and len(value) <= MAX_VALUE and VALIDATORS[key](value)}


def saved_language() -> str:
    """Language of the dashboard (saved setting), else the OS display language, for terminal messages."""
    saved = load_inputs().get("locale")
    if saved in ("ko", "en"):
        return saved
    try:
        import ctypes
        return "ko" if ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0xFF == 0x12 else "en"
    except (AttributeError, OSError):
        return "en"


def save_inputs(values: dict) -> None:
    if not valid_inputs(values):
        raise ValueError("Invalid dashboard inputs.")
    F_INPUTS.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=F_INPUTS.parent, prefix="inputs-", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(values, stream, ensure_ascii=False, indent=1)
        os.replace(temporary, F_INPUTS)
    except OSError:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
