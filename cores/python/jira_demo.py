"""Demo mode: the real dashboard with built-in dummy data. No Jira connection, user ID, or password is needed.

Only the Jira calls are replaced (project list, project lookup, reporter search, and the year's issues). The page,
server, filters, charts, exports, and saved inputs are the same code that runs against a real Jira. Demo inputs are
kept in their own git-ignored file so they never overwrite the saved inputs of a real session.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import date, datetime, timedelta
import os
import random
import webbrowser

import jira_dashboard_server
import jira_dashboard_service
import jira_inputs
import jira_paths
from jira_autologin import MemoryAutoLogin
from jira_credentials import Credentials
from jira_issue_monthly import TZ

# (key, name, issues per year) - fictional.
PROJECTS = [
    ("ATLAS", "Atlas Platform", 900), ("NOVA", "Nova Mobile", 700), ("ORBIT", "Orbit Analytics", 520),
    ("PULSE", "Pulse Monitoring", 430), ("LUMEN", "Lumen Imaging", 610), ("VERTEX", "Vertex Controls", 380),
    ("HELIX", "Helix Firmware", 760), ("KITE", "Kite 연구소", 240), ("MARBLE", "Marble Web", 480),
    ("QUARTZ", "Quartz Service", 350), ("RIVER", "River Connectivity", 290), ("SUMMIT", "Summit 품질관리", 560),
]
# (user ID, display name) - fictional.
USERS = [
    ("hong01", "홍길동"), ("kim02", "김민수"), ("lee03", "이서연"), ("park04", "박지훈"),
    ("choi05", "최유진"), ("jung06", "정하늘"), ("kang07", "강도윤"), ("yoon08", "윤서아"),
]
DEFAULT_PROJECTS = ["ATLAS", "NOVA", "HELIX"]
DEFAULT_REPORTERS = [user for user, _ in USERS]


def _poisson(generator: random.Random, lam: float) -> int:
    if lam <= 0:
        return 0
    if lam > 30:
        return max(0, round(generator.gauss(lam, lam ** .5)))
    limit, product, count = pow(2.718281828459045, -lam), generator.random(), 0
    while product > limit:
        count += 1
        product *= generator.random()
    return count


def _profile(key: str, year: int, days: int) -> dict:
    """The character of one dummy project, fixed by its key and year so every run shows the same data."""
    generator = random.Random(f"profile:{year}:{key}")
    weights = [generator.random() ** 2 + .04 for _ in USERS]  # a few reporters file most of the issues
    return {
        "trend": generator.uniform(-.45, .65),  # creation grows or shrinks over the year
        "spikes": [(generator.randrange(15, days - 10), generator.uniform(1.4, 3.6), generator.randint(3, 10))
                   for _ in range(generator.randint(1, 3))],  # release and incident bursts: (day, extra height, width)
        "quiet": (generator.randrange(20, days - 30), generator.randint(6, 14), generator.uniform(.25, .6)),  # a holiday lull
        "resolve_rate": generator.uniform(.5, .95),  # share of issues that get closed at all
        "rate_drift": generator.uniform(-.3, .15),  # closing capacity falls (debt builds) or recovers over the year
        "lag_mean": generator.uniform(5, 42),  # days to close
        "sprint": generator.choice([7, 14, 14, 21]), "sprint_offset": generator.randrange(21),
        "sprint_batch": generator.uniform(.15, .7),  # share of issues closed together at the sprint end
        "users": [user for user, _ in USERS], "weights": weights,
    }


def _issues(key: str, year: int, scale: int):
    """Deterministic dummy issues of one project: (reporter, created date, resolved date or None)."""
    days = (date(year + 1, 1, 1) - date(year, 1, 1)).days
    profile, generator = _profile(key, year, days), random.Random(f"{year}:{key}")
    today = datetime.now(TZ).date()
    window = range(-92, days)  # the last quarter of the previous year can still be resolved this year

    def activity(day: int) -> float:
        value = 1 + profile["trend"] * (day / days - .5)
        for center, height, width in profile["spikes"]:
            value += height * pow(2.718281828459045, -((day - center) / width) ** 2 / 2)
        start, length, factor = profile["quiet"]
        if start <= day < start + length:
            value *= factor
        return max(.05, value)

    mean = sum(activity(day) for day in window) / len(window)
    issues = []
    for day in window:
        created = date(year, 1, 1) + timedelta(days=day)
        if created > today:
            break
        weekday_factor = .22 if created.weekday() >= 5 else 1.15
        noise = generator.lognormvariate(0, .4)
        for _ in range(_poisson(generator, scale / 260 * weekday_factor * activity(day) / mean * noise)):
            rate = min(.97, max(.2, profile["resolve_rate"] + profile["rate_drift"] * (day / days - .5)))
            resolved = None
            if generator.random() < rate:
                lag = 1 + int(generator.expovariate(1 / profile["lag_mean"]))
                if generator.random() < .12:  # quick fixes
                    lag = generator.randint(0, 2)
                resolved = created + timedelta(days=lag)
                if generator.random() < profile["sprint_batch"]:  # closed together when the sprint ends
                    resolved += timedelta(days=-(resolved.toordinal() + profile["sprint_offset"]) % profile["sprint"])
            reporter = generator.choices(profile["users"], profile["weights"])[0]
            issues.append((reporter, created, resolved if resolved and resolved <= today else None))
    return issues


def fetch_year_issues(projects, year, reporters, credentials):
    wanted = {name.casefold() for name in reporters}
    known = {key: scale for key, _, scale in PROJECTS}
    records = [(key, created, resolved) for key in projects for reporter, created, resolved in _issues(key, year, known.get(key, 300))
               if reporter.casefold() in wanted]
    return records, 1


def fetch_projects(credentials):
    return sorted(({"key": key, "name": name} for key, name, _ in PROJECTS), key=lambda project: (project["name"].casefold(), project["key"]))


def fetch_project(credentials, key):
    for known, name, _ in PROJECTS:
        if known == key.upper():
            return {"key": known, "name": name}
    raise RuntimeError("Jira HTTP 404: Request rejected")


def search_reporters(credentials, query):
    if not isinstance(query, str) or len(query) > 100 or any(ord(c) < 32 or ord(c) == 127 for c in query):
        raise ValueError("Invalid reporter query.")
    needle = query.strip().casefold()
    matches = [{"name": user, "displayName": name} for user, name in USERS if needle in ("", ".") or needle in user or needle in name.casefold()]
    return sorted(matches, key=lambda user: (user["displayName"].casefold(), user["name"]))


@contextmanager
def demo_environment(inputs_file=None):
    """Swap the Jira calls for dummy data and the saved-inputs file for a demo-only file; restore everything on exit."""
    replacements = [
        (jira_dashboard_service, "fetch_year_issues", fetch_year_issues),
        (jira_dashboard_server, "fetch_projects", fetch_projects),
        (jira_dashboard_server, "fetch_project", fetch_project),
        (jira_dashboard_server, "search_reporters", search_reporters),
        (jira_inputs, "F_INPUTS", inputs_file or jira_paths.D_LOCAL / "demo-inputs.json"),
    ]
    originals = [(module, name, getattr(module, name)) for module, name, _ in replacements]
    for module, name, value in replacements:
        setattr(module, name, value)
    try:
        yield
    finally:
        for module, name, value in originals:
            setattr(module, name, value)


def open_browser(url: str) -> bool:
    try:
        if webbrowser.open_new_tab(url):
            return True
    except (OSError, webbrowser.Error):
        pass
    startfile = getattr(os, "startfile", None)
    if startfile is None:
        return False
    try:
        startfile(url)
        return True
    except OSError:
        return False


def main():
    parser = argparse.ArgumentParser(description="Jira dashboard demo with dummy data (no Jira connection needed)")
    parser.add_argument("--port", type=int, default=0, help="Local port (default: automatically allocated)")
    parser.add_argument("--no-open", action="store_true", help="Print the dashboard URL without opening a browser")
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error("port must be between 0 and 65535")
    with demo_environment():
        credentials = Credentials("https://demo.invalid", "demo", "demo-not-a-real-password")
        with jira_dashboard_server.DashboardServer(credentials, DEFAULT_PROJECTS, DEFAULT_REPORTERS, args.port, autologin=MemoryAutoLogin()) as server:
            print(f"Dashboard (DEMO): {server.origin}/", flush=True)
            print("DEMO MODE: dummy data only; no Jira connection. Keep this terminal open; press Ctrl+C to stop.", flush=True)
            if not args.no_open and not open_browser(server.origin + "/"):
                print("Open the dashboard URL above in your browser.")
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                print("Demo stopped.")
