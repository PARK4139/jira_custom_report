"""Allowlisted runtime evidence, excluding URLs, identities, queries, and secrets."""
from datetime import datetime, timezone
import json
from uuid import uuid4

from jira_paths import F_RUNTIME_LOG

RUN_ID = uuid4().hex


def record_event(event: str, outcome: str, count: int | None = None, http_status: int | None = None):
    snapshot = {"timestamp": datetime.now(timezone.utc).isoformat(), "run_id": RUN_ID,
                "event": event, "outcome": outcome}
    if count is not None:
        snapshot["count"] = count
    if http_status is not None:
        snapshot["http_status"] = http_status
    F_RUNTIME_LOG.parent.mkdir(parents=True, exist_ok=True)
    with F_RUNTIME_LOG.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(snapshot) + "\n")
