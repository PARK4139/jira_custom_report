"""One paged Jira search per report year, aggregated locally into every period bucket."""
from __future__ import annotations

import base64
from bisect import bisect_right
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
import json
from urllib.request import Request

from jira_audit import record_event
from jira_credentials import Credentials, validate_url
from jira_issue_monthly import TZ, request_json
from jira_jql_log import log_jql
from jira_periods import period_ranges

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


def _search_page(credentials: Credentials, jql: str, start_at: int, max_results: int,
                 fields: list[str] | None = None) -> dict:
    endpoint = validate_url(url=credentials.url, allow_insecure_http=credentials.allow_insecure_http) + "/rest/api/2/search"
    auth = base64.b64encode(f"{credentials.email}:{credentials.token}".encode()).decode()
    payload = {"jql": jql, "fields": fields or ["project", "created", "resolutiondate"],
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


def count_unresolved_at_period_ends(projects: list[str], year: int, reporters: list[str],
                                    credentials: Credentials, period: str) -> tuple[dict[str, list[dict]], int]:
    """Replay resolution changelogs, including issues whose empty resolution was never changed."""
    keys = ", ".join(json.dumps(project, ensure_ascii=False) for project in projects)
    names = ", ".join(json.dumps(name, ensure_ascii=False) for name in reporters)
    lower, upper = date(year, 1, 1), date(year + 1, 1, 1)
    jql = (f"project IN ({keys}) AND reporter IN ({names}) AND created < \"{upper}\" AND "
           f'(resolution IS EMPTY OR resolutiondate >= "{lower}" OR '
           f'resolution CHANGED DURING ("{lower}", "{upper}")) ORDER BY key ASC')
    first = _search_page(credentials, jql, 0, PAGE_SIZE, ["project", "created", "resolution"])
    total = first["total"]
    size = first.get("maxResults") if type(first.get("maxResults")) is int and first["maxResults"] > 0 else PAGE_SIZE
    if total > len(first["issues"]) and not first["issues"]:
        raise RuntimeError("Jira pagination did not advance before reaching the total.")
    starts = list(range(len(first["issues"]), total, size))
    pages = [first]
    if starts:
        with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(starts))) as pool:
            pages += list(pool.map(lambda start: _search_page(credentials, jql, start, size, ["project", "created", "resolution"]), starts))
    candidates = [issue for page in pages for issue in page["issues"]]
    if len({issue.get("id") for issue in candidates}) != total:
        raise RuntimeError("Jira results changed during the history query. Retry the report.")
    base = validate_url(url=credentials.url, allow_insecure_http=credentials.allow_insecure_http)
    auth = base64.b64encode(f"{credentials.email}:{credentials.token}".encode()).decode()
    def history_page(identity, start_at, count):
        endpoint = f"{base}/rest/api/2/issue/{identity}/changelog?startAt={start_at}&maxResults={count}"
        request = Request(endpoint, headers={"Authorization": f"Basic {auth}", "Accept": "application/json"})
        try:
            return request_json(request=request, event="issue_changelog"), 1
        except RuntimeError as exc:
            if "Jira HTTP 404:" not in str(exc):
                raise
        # Jira Server 7.3 has changelog expansion on GET issue but does not
        # expose the newer standalone issue/{id}/changelog endpoint.
        endpoint = f"{base}/rest/api/2/issue/{identity}?fields=project,created,resolution&expand=changelog"
        request = Request(endpoint, headers={"Authorization": f"Basic {auth}", "Accept": "application/json"})
        issue_detail = request_json(request=request, event="issue_changelog_expand")
        changelog = issue_detail.get("changelog")
        if not isinstance(changelog, dict):
            raise RuntimeError("Jira issue response has no expanded changelog.")
        histories = changelog.get("histories")
        total_changes = changelog.get("total")
        if not isinstance(histories, list) or type(total_changes) is not int:
            raise RuntimeError("Jira expanded changelog response has an invalid shape.")
        if start_at + len(histories) < total_changes:
            raise RuntimeError("Jira Server returned an incomplete expanded changelog; update Jira or reduce the issue history.")
        return {"histories": histories, "total": total_changes}, 2

    def histories(issue):
        identity = issue.get("id")
        if not isinstance(identity, str) or not identity.isdigit():
            raise RuntimeError("Jira returned an invalid issue identity for history lookup.")
        values, start_at, count, requests = [], 0, 100, 0
        while True:
            result, sent = history_page(identity, start_at, count)
            requests += sent
            batch = result.get("values", result.get("histories"))
            total_changes = result.get("total")
            if not isinstance(batch, list) or type(total_changes) is not int:
                raise RuntimeError("Jira issue changelog response has an invalid shape.")
            values.extend(batch)
            if len(values) >= total_changes:
                break
            if not batch:
                raise RuntimeError("Jira changelog pagination did not advance.")
            start_at += len(batch)
        events = []
        for history in values:
            changed = _local_date(history.get("created"))
            for item in history.get("items", []):
                if item.get("field", "").casefold() == "resolution":
                    if "to" not in item and "toString" not in item:
                        raise RuntimeError("Jira returned an incomplete resolution history item.")
                    old_value = item.get("fromString") or item.get("from")
                    new_value = item.get("toString") or item.get("to")
                    if changed is None:
                        raise RuntimeError("Jira returned a resolution change without a timestamp.")
                    events.append((changed, bool(old_value), bool(new_value)))
        return issue, sorted(events, key=lambda event: event[0]), requests
    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, max(1, len(candidates)))) as pool:
        histories_by_issue = list(pool.map(histories, candidates)) if candidates else []
    buckets = period_ranges(year, period)
    grouped = {project: [] for project in projects}
    project_lookup = {project.casefold(): project for project in projects}
    snapshots = {(project, bucket['start']): 0 for project in projects for bucket in buckets}
    history_requests = 0
    for issue, events, issue_requests in histories_by_issue:
        history_requests += issue_requests
        fields = issue.get('fields')
        project_data = fields.get('project') if isinstance(fields, dict) else None
        project = project_lookup.get(project_data.get('key', '').casefold()) if isinstance(project_data, dict) else None
        created = _local_date(fields.get('created')) if isinstance(fields, dict) else None
        if project is None or created is None:
            raise RuntimeError("Jira issue fields are invalid during resolution history lookup.")
        for bucket in buckets:
            as_of = date.fromisoformat(bucket['end']) - timedelta(days=1)
            if created > as_of:
                continue
            current_resolution = fields.get('resolution')
            resolved = current_resolution is not None
            if events:
                resolved = events[0][1]
            for changed, _old_resolved, new_resolved in events:
                if changed <= as_of:
                    resolved = new_resolved
                else:
                    break
            if not resolved:
                snapshots[(project, bucket['start'])] += 1
    for project in projects:
        for bucket in buckets:
            grouped[project].append(dict(bucket, unresolved=snapshots[(project, bucket['start'])],
                                         queries={'unresolved': jql + '\n\nResolution history replayed from Jira changelogs.'}))
    return grouped, len(pages) + history_requests


def count_buckets(records, year: int, period: str) -> list[dict]:
    rows = [dict(bucket, created=0, resolved=0) for bucket in period_ranges(year, period)]
    starts = [date.fromisoformat(row["start"]) for row in rows]
    lower, upper = date(year, 1, 1), date(year + 1, 1, 1)
    for _, created, resolved in records:
        for field, value in (("created", created), ("resolved", resolved)):
            if value is not None and lower <= value < upper:
                rows[bisect_right(starts, value) - 1][field] += 1
    return rows
