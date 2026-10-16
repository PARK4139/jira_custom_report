#!/usr/bin/env python3
"""On-premises Jira: weekly, fortnightly, monthly, and yearly issue counts.

Credentials: hidden password prompt by default; explicit opt-in Windows storage.
Produces aggregate-only CSV + single-file offline HTML, no individual issue data.
"""
from __future__ import annotations

import argparse
import base64
import csv
from datetime import date, datetime
import json
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener
from zoneinfo import ZoneInfo
import webbrowser

from jira_paths import D_OUTPUTS
from jira_audit import record_event
from jira_jql_log import log_jql
from jira_report_view import render_html
from jira_credentials import (Credentials, delete_credentials, load_credentials, prompt_credentials,
                              save_credentials, validate_profile, validate_url)
from jira_settings import Settings, complete_settings, load_settings, save_settings
from jira_periods import BASE_PERIODS, PERIODS, QUARTERS, period_ranges, period_jql

TZ = ZoneInfo("Asia/Seoul")


def build_monthly_jql(project: str, year: int, reporters: list[str], month: int, date_field: str) -> str:
    if date_field not in ("created", "resolved"):
        raise ValueError("Monthly JQL supports only created or resolved.")
    if not 1 <= month <= 12:
        raise ValueError("Month must be between 1 and 12.")
    lower = date(year, month, 1)
    upper = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    reporters_clause = ", ".join(json.dumps(r, ensure_ascii=False) for r in reporters)
    return (f'project = "{project}" AND reporter IN ({reporters_clause}) '
            f'AND {date_field} >= "{lower}" AND {date_field} < "{upper}"')


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # urllib may forward Authorization to another host on a redirect.
        return None


def request_json(request: Request, event: str, expected_type: type = dict) -> dict | list:
    opener = build_opener(NoRedirect())
    record_event(event=event, outcome="request")
    try:
        with opener.open(request, timeout=40) as response:
            result = json.load(response)
    except HTTPError as exc:
        code = exc.code
        exc.close()
        record_event(event=event, outcome="http_error", http_status=code)
        hints = {401: "Invalid user ID or password, or Basic authentication is disabled on this server.",
                 403: "Check account project permissions and server authentication policy.",
                 429: "Rate limit reached; retry later."}
        raise RuntimeError(f"Jira HTTP {code}: {hints.get(code, 'Request rejected; check site and request settings. Redirects are disabled.')}") from None
    except (URLError, TimeoutError, OSError):
        record_event(event=event, outcome="network_error")
        raise RuntimeError("Jira connection failed; check network and HTTPS certificates.") from None
    except (ValueError, UnicodeError):
        record_event(event=event, outcome="invalid_json")
        raise RuntimeError("Jira returned an invalid JSON response.") from None
    if not isinstance(result, expected_type):
        record_event(event=event, outcome="invalid_response")
        raise RuntimeError("Jira response has an invalid shape.")
    record_event(event=event, outcome="response")
    return result


def fetch_issues(url: str, email: str, token: str, jql: str, *, allow_insecure_http: bool = False):
    endpoint = validate_url(url=url, allow_insecure_http=allow_insecure_http) + "/rest/api/2/search"
    auth = base64.b64encode(f"{email}:{token}".encode()).decode()
    start_at = 0
    while True:
        payload = {"jql": jql, "fields": ["created", "resolutiondate"],
                   "maxResults": 100, "startAt": start_at}
        req = Request(
            endpoint, data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Basic {auth}", "Accept": "application/json", "Content-Type": "application/json"},
            method="POST",
        )
        result = request_json(request=req, event="issue_search")
        issues = result.get("issues")
        total = result.get("total")
        log_jql(jql, start_at, total if type(total) is int else None)
        offset = result.get("startAt")
        if (not isinstance(issues, list) or type(total) is not int or total < 0
                or type(offset) is not int or offset != start_at):
            raise RuntimeError("Jira issue-search response has an invalid shape or pagination offset.")
        record_event(event="issue_page", outcome="received", count=len(issues))
        for issue in issues:
            if not isinstance(issue, dict) or not isinstance(issue.get("fields"), dict):
                raise RuntimeError("Jira issue fields are invalid.")
            yield issue
        start_at += len(issues)
        if start_at >= total:
            break
        if not issues:
            raise RuntimeError("Jira pagination did not advance before reaching the total.")


def collect_monthly_counts(project: str, year: int, reporters: list[str], credentials: Credentials) -> list[dict]:
    counts = [{"month": f"{m:02d}", "created": 0, "resolved": 0} for m in range(1, 13)]
    # Execute all 12 created queries, then all 12 resolved queries, as requested.
    for date_field in ("created", "resolved"):
        for month in range(1, 13):
            jql = build_monthly_jql(project=project, year=year, reporters=reporters, month=month, date_field=date_field)
            issues = fetch_issues(url=credentials.url, email=credentials.email, token=credentials.token,
                                  jql=jql, **({"allow_insecure_http": True} if credentials.allow_insecure_http else {}))
            count = sum(1 for _ in issues)
            counts[month - 1][date_field] = count
            record_event(event="monthly_query", outcome=f"{date_field}_{month:02d}", count=count)
            print(f"{project} {year}-{month:02d} {date_field}: {count}")
    return counts


def write_csv(path: Path, rows: list[dict]):
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["month", "created", "resolved"])
        writer.writeheader()
        writer.writerows(rows)


def collect_period_counts(project: str, year: int, reporters: list[str], credentials: Credentials, period: str) -> list[dict]:
    rows = [dict(bucket, created=0, resolved=0) for bucket in period_ranges(year, period)]
    for field in ("created", "resolved"):
        for row in rows:
            jql = period_jql(project, reporters, row["start"], row["end"], field)
            row[field] = sum(1 for _ in fetch_issues(credentials.url, credentials.email, credentials.token, jql,
                                                      **({"allow_insecure_http": True} if credentials.allow_insecure_http else {})))
            record_event(event="period_query", outcome=f"{period}_{field}", count=row[field])
            print(f"{project} {period} {row['start']} {field}: {row[field]}")
    if period in QUARTERS:
        # Cumulative from January 1: count what was created/resolved before the quarter starts.
        year_start, carry = f"{year}-01-01", {"created": 0, "resolved": 0}
        for field in carry:
            if rows[0]["start"] != year_start:
                carry[field] = sum(1 for _ in fetch_issues(credentials.url, credentials.email, credentials.token,
                                                           period_jql(project, reporters, year_start, rows[0]["start"], field),
                                                           **({"allow_insecure_http": True} if credentials.allow_insecure_http else {})))
        rows[0]["carry"] = carry
    return rows


def write_period_csv(path: Path, rows: list[dict]):
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=["label", "start", "end", "created", "resolved"], extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)





def write_html(path: Path, project: str, year: int, counts: list[dict], reporters: list[str], periods: dict | None = None):
    path.write_text(render_html(project, year, counts, reporters, periods), encoding="utf-8")


def open_html_report(path: Path) -> bool:
    f_report = path.resolve()
    if not f_report.is_file():
        record_event(event="html_preview", outcome="missing_file")
        print(f"HTML preview unavailable: saved file not found: {f_report}", file=sys.stderr)
        return False
    try:
        opened = webbrowser.open_new_tab(f_report.as_uri())
    except (OSError, webbrowser.Error):
        opened = False
    record_event(event="html_preview", outcome="dispatched" if opened else "launch_failed")
    if opened:
        print(f"Opened HTML report in the default browser: {f_report}")
    else:
        print(f"Could not open the browser automatically. Your report is saved; open it manually: {f_report}", file=sys.stderr)
    return bool(opened)


def export_main():
    parser = argparse.ArgumentParser(description="Jira Server/Data Center issue trend report")
    parser.add_argument("--periods", nargs="+", choices=PERIODS, default=list(BASE_PERIODS), help="Reporting periods to query (default: 1week 2week monthly yearly; add q1-q4 for quarters)")
    parser.add_argument("--year", type=int, help="Report year (saved in the local profile)")
    parser.add_argument("--project", nargs="+", help="Jira project keys")
    parser.add_argument("--reporter", nargs="+", help="Jira reporter user IDs or names")
    parser.add_argument("--output-dir", default=str(D_OUTPUTS))
    parser.add_argument("--no-open", action="store_true", help="Save reports without opening HTML in the default browser")
    parser.add_argument("--profile", default="default", help="Local credential profile")
    parser.add_argument("--url", "--site-url", dest="site_url", help="HTTPS Jira server base URL (including context path if needed)")
    parser.add_argument("--id", "--email", dest="email", help="Jira user ID (general setting)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--configure", action="store_true", help="Save general settings only; never requests or saves a password")
    mode.add_argument("--save-credentials", action="store_true", help="Explicitly enter and save a password in Windows Credential Manager")
    mode.add_argument("--use-saved-credentials", action="store_true", help="Explicitly read the selected Windows credential profile")
    mode.add_argument("--delete-credentials", action="store_true", help="Delete the local credential profile")
    args = parser.parse_args()
    validate_profile(args.profile)
    if args.delete_credentials:
        delete_credentials(profile=args.profile)
        record_event(event="credentials", outcome="deleted")
        print("Saved credential profile deleted. General settings are retained.")
        return
    # --configure deliberately ignores a corrupt prior file so it can repair the profile.
    saved = None if args.configure else load_settings(profile=args.profile)
    settings = complete_settings(arguments=args, saved=saved)
    if saved != settings:
        save_settings(profile=args.profile, settings=settings)
    if args.configure:
        print("General settings saved. No password was requested or stored.")
        return
    if args.use_saved_credentials:
        credentials = load_credentials(profile=args.profile)
        if credentials.url != settings.site_url or credentials.email != settings.email:
            raise RuntimeError("Saved credentials do not match this server's user ID. Use --save-credentials to replace them.")
        record_event(event="credentials", outcome="explicit_vault")
    else:
        credentials = prompt_credentials(url=settings.site_url, email=settings.email)
        record_event(event="credentials", outcome="hidden_prompt")
    if args.save_credentials:
        save_credentials(profile=args.profile, credentials=credentials)
        record_event(event="credentials", outcome="explicit_save")
        print("Password saved in Windows Credential Manager on this PC. Use --use-saved-credentials to read it.")
        return
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    html_reports = []
    for project in settings.projects:
        datasets = {}
        counts = []
        for period in dict.fromkeys(args.periods):
            if period == "monthly":
                counts = collect_monthly_counts(project, settings.year, settings.reporters, credentials)
                datasets[period] = [dict(bucket, created=row["created"], resolved=row["resolved"])
                                    for bucket, row in zip(period_ranges(settings.year, period), counts)]
                write_csv(out / f"{project}_{settings.year}_monthly_issues.csv", counts)
            else:
                datasets[period] = collect_period_counts(project, settings.year, settings.reporters, credentials, period)
                write_period_csv(out / f"{project}_{settings.year}_{period}_issues.csv", datasets[period])
        html_path = out / f"{project}_{settings.year}_monthly_issues.html"
        write_html(path=html_path, project=project, year=settings.year, counts=counts,
                   reporters=settings.reporters, periods=datasets)
        query_count = sum(len(rows) * 2 for rows in datasets.values())
        record_event(event="report_generated", outcome="success", count=query_count)
        print(f"{project}: periods={', '.join(datasets)}, queries={query_count}")
        print(f"CSV directory: {out.resolve()}\nHTML: {html_path.resolve()}")
        html_reports.append(html_path)
    if args.no_open:
        record_event(event="html_preview", outcome="disabled", count=len(html_reports))
    else:
        for html_path in html_reports:
            open_html_report(path=html_path)


def main():
    from jira_web import main as web_main
    web_main()


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, EOFError) as exc:
        raise SystemExit(str(exc)) from None
    except KeyboardInterrupt:
        raise SystemExit("취소했습니다.") from None
