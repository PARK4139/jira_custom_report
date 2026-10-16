"""Native JQL log (logs/jql.jsonl): the exact query text sent to Jira; never credentials or URLs."""
from datetime import datetime, timezone
import json

from jira_audit import RUN_ID
from jira_paths import F_JQL_LOG


def log_jql(jql: str, start_at: int, total: int | None = None):
    entry = {"timestamp": datetime.now(timezone.utc).isoformat(), "run_id": RUN_ID,
             "jql": jql, "start_at": start_at}
    if total is not None:
        entry["total"] = total
    try:
        F_JQL_LOG.parent.mkdir(parents=True, exist_ok=True)
        with F_JQL_LOG.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass  # Diagnostics must never break a report.
