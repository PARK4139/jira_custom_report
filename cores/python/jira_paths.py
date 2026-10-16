"""Standalone project paths; no dependency on a developer's private checkout."""
from pathlib import Path

D_SOURCE_DIR = Path(__file__).resolve().parent
D_PROJECT = D_SOURCE_DIR.parents[1] if D_SOURCE_DIR.name == "python" and D_SOURCE_DIR.parent.name == "cores" else D_SOURCE_DIR
D_LOCAL = D_PROJECT / ".local"
D_OUTPUTS = D_PROJECT / "outputs"
F_RUNTIME_LOG = D_LOCAL / "runtime.jsonl"
D_LOGS = D_PROJECT / "logs"
F_JQL_LOG = D_LOGS / "jql.jsonl"


def get_profile_path(profile: str) -> Path:
    from jira_credentials import validate_profile
    return D_LOCAL / f"{validate_profile(profile=profile)}.toml"
