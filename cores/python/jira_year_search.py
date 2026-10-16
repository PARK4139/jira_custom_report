"""One paged Jira search per report year, aggregated locally into every period bucket."""
from __future__ import annotations

import base64
from bisect import bisect_right
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
import json
from urllib.request import Request

from jira_audit import record_event
from jira_credentials import Credentials, validate_url
from jira_issue_monthly import TZ, request_json
from jira_jql_log import log_jql
from jira_periods import QUARTERS, period_ranges

PAGE_SIZE = 1000
MAX_WORKERS = 8


def year_jql(projects: list[str], year: int, reporters: list[str]) -> str:
    if not projects or not reporters:
        raise ValueError("Select at least one project and one reporter.")
    keys = ", ".join(json.dumps(project, ensure_ascii=False) for project in projects)
    names = ", ".join(json.dumps(name, ensure_ascii=False) for name in reporters)
    lower, upper = date(year, 1, 1), date(year + 1, 1, 1)
    return (f"project IN ({keys}) AND reporter IN ({names}) "
            f'AND ((created >= "{lower}" AND created < "{upper}") '
            f'OR (resolved >= "{lower}" AND resolved < "{upper}")) ORDER BY key ASC')


def _search_page(credentials: Credentials, jql: str, start_at: int, max_results: int) -> dict:
    endpoint = validate_url(url=credentials.url, allow_insecure_http=credentials.allow_insecure_http) + "/rest/api/2/search"
    auth = base64.b64encode(f"{credentials.email}:{credentials.token}".encode()).decode()
    payload = {"jql": jql, "fields": ["project", "created", "resolutiondate"],
               "maxResults": max_results, "startAt": start_at}
    request = Request(endpoint, data=json.dumps(payload).encode("utf-8"), method="POST",
                      headers={"Authorization": f"Basic {auth}", "Accept": "application/json",
                               "Content-Type": "application/json"})
    result = request_json(request=request, event="issue_search")
    issues, total, offset = result.get("issues"), result.get("total"), result.get("startAt")
    log_jql(jql, start_at, total if type(total) is int else None)
    if (not isinstance(issues, list) or type(total) is not int or total < 0
            or type(offset) is not int or offset != start_at):
        raise RuntimeError("Jira issue-search response has an invalid shape or pagination offset.")
    record_event(event="issue_page", outcome="received", count=len(issues))
    return result


def _local_date(value) -> date | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise RuntimeError("Jira issue dates are invalid.")
    try:
        moment = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%f%z")
    except ValueError:
        try:
            moment = datetime.fromisoformat(value)
        except ValueError:
            raise RuntimeError("Jira issue dates are invalid.") from None
    if moment.tzinfo is None:
        raise RuntimeError("Jira issue dates are invalid.")
    return moment.astimezone(TZ).date()


def _issue_record(issue, projects: dict[str, str]) -> tuple[str, str, date | None, date | None]:
    fields = issue.get("fields") if isinstance(issue, dict) else None
    project = fields.get("project") if isinstance(fields, dict) else None
    key = project.get("key") if isinstance(project, dict) else None
    identity = issue.get("id") if isinstance(issue, dict) else None
    if not isinstance(identity, str) or not isinstance(key, str) or key.casefold() not in projects:
        raise RuntimeError("Jira issue fields are invalid.")
    return identity, projects[key.casefold()], _local_date(fields.get("created")), _local_date(fields.get("resolutiondate"))


def fetch_year_issues(projects: list[str], year: int, reporters: list[str],
                      credentials: Credentials) -> tuple[list[tuple[str, date | None, date | None]], int]:
    """Return (project, created date, resolved date) per issue and the number of search requests sent."""
    jql = year_jql(projects, year, reporters)
    first = _search_page(credentials, jql, 0, PAGE_SIZE)
    total = first["total"]
    size = first.get("maxResults")
    if type(size) is not int or size <= 0:
        size = len(first["issues"]) or PAGE_SIZE
    if total > len(first["issues"]) and not first["issues"]:
        raise RuntimeError("Jira pagination did not advance before reaching the total.")
    starts = list(range(len(first["issues"]), total, size))
    pages = [first]
    if starts:
        with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(starts))) as pool:
            pages += list(pool.map(lambda start: _search_page(credentials, jql, start, size), starts))
    keys = {project.casefold(): project for project in projects}
    records = {}
    for page in pages:
        for issue in page["issues"]:
            identity, *record = _issue_record(issue, keys)
            records[identity] = tuple(record)
    if len(records) != total:
        raise RuntimeError("Jira results changed during the query. Retry the report.")
    record_event(event="year_search", outcome="complete", count=total)
    return list(records.values()), len(pages)


def count_buckets(records, year: int, period: str) -> list[dict]:
    rows = [dict(bucket, created=0, resolved=0) for bucket in period_ranges(year, period)]
    starts = [date.fromisoformat(row["start"]) for row in rows]
    lower, upper = starts[0], date.fromisoformat(rows[-1]["end"])
    carry = {"created": 0, "resolved": 0}
    for _, created, resolved in records:
        for field, value in (("created", created), ("resolved", resolved)):
            if value is None:
                continue
            if lower <= value < upper:
                rows[bisect_right(starts, value) - 1][field] += 1
            elif period in QUARTERS and date(year, 1, 1) <= value < lower:
                carry[field] += 1
    if period in QUARTERS:
        # Quarters are cumulative from January 1 like every other period: earlier quarters are the starting level.
        rows[0]["carry"] = carry
    return rows
