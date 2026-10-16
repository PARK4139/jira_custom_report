"""Allowlisted nonsecret report profiles, serialized with TOML libraries."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import os
from pathlib import Path
import sys
import tempfile
import tomllib

import tomli_w

from jira_audit import record_event
from jira_credentials import validate_url
from jira_paths import get_profile_path


@dataclass(frozen=True)
class Settings:
    site_url: str
    email: str
    projects: list[str]
    reporters: list[str]
    year: int
    allow_insecure_http: bool = False

    def __post_init__(self):
        if not isinstance(self.site_url, str):
            raise ValueError("Site URL must be text.")
        object.__setattr__(self, "site_url", validate_url(url=self.site_url, allow_insecure_http=self.allow_insecure_http))
        if (not isinstance(self.email, str) or not self.email.strip() or ":" in self.email
                or any(ord(c) < 32 or ord(c) == 127 for c in self.email)):
            raise ValueError("Enter a valid Jira user ID.")
        for entries in (self.projects, self.reporters):
            if (not isinstance(entries, list) or not entries or
                    not all(isinstance(entry, str) and entry.strip() and
                            not any(ord(c) < 32 or ord(c) == 127 for c in entry) for entry in entries)):
                raise ValueError("Projects and reporters must be nonempty lists of text.")
        if not all(all(c.isascii() and (c.isalnum() or c in "_-") for c in project) for project in self.projects):
            raise ValueError("Project keys allow only ASCII letters, digits, underscore, and hyphen.")
        if type(self.year) is not int or not 2 <= self.year <= 9998:
            raise ValueError("Year must be an integer between 2 and 9998.")



def load_settings(profile: str, *, allow_insecure_http: bool = False) -> Settings | None:
    f_profile = get_profile_path(profile=profile)
    if not f_profile.exists():
        return None
    try:
        with f_profile.open("rb") as stream:
            document = tomllib.load(stream)
        if set(document) != {"jira", "report"}:
            raise ValueError
        jira = document["jira"]
        report = document["report"]
        if (not isinstance(jira, dict) or not isinstance(report, dict)
                or set(jira) - {"site_url", "email", "cloud_id"}
                or not {"projects", "reporters"} <= set(report)
                or set(report) - {"projects", "reporters", "year"}):
            raise ValueError
        # Ignore legacy cloud_id when migrating old nonsecret profiles.
        settings = Settings(site_url=jira["site_url"], email=jira["email"],
                            projects=report["projects"], reporters=report["reporters"], year=report.get("year", datetime.now().year),
                            allow_insecure_http=allow_insecure_http)
    except (ValueError, TypeError, KeyError, OSError):
        record_event(event="settings", outcome="invalid")
        raise RuntimeError("Invalid local profile. Use --configure to replace it; token/password fields are forbidden.") from None
    record_event(event="settings", outcome="loaded")
    return settings


def save_settings(profile: str, settings: Settings):
    # Build a fresh document from named general fields; Credentials is never serialized here.
    document = {"jira": {"site_url": settings.site_url, "email": settings.email},
                "report": {"projects": settings.projects, "reporters": settings.reporters, "year": settings.year}}
    f_profile = get_profile_path(profile=profile)
    f_profile.parent.mkdir(parents=True, exist_ok=True)
    f_pending = None
    try:
        # A sibling file permits atomic replacement on the same filesystem.
        with tempfile.NamedTemporaryFile(dir=f_profile.parent, prefix=f_profile.name + ".", suffix=".pending", delete=False) as stream:
            f_pending = Path(stream.name)
            tomli_w.dump(document, stream)
        os.replace(f_pending, f_profile)
    finally:
        if f_pending is not None:
            f_pending.unlink(missing_ok=True)
    record_event(event="settings", outcome="saved")


def complete_settings(arguments, saved: Settings | None) -> Settings:
    site_url = arguments.site_url or (saved.site_url if saved else None)
    email = arguments.email or (saved.email if saved else None)
    projects = arguments.project or (saved.projects if saved else None)
    reporters = arguments.reporter or (saved.reporters if saved else None)
    year = arguments.year if arguments.year is not None else saved.year if saved else datetime.now().year
    missing = not all((site_url, email, projects, reporters))
    if missing:
        if not sys.stdin.isatty():
            raise RuntimeError("Profile is incomplete. Run --configure in an interactive terminal or supply general settings as arguments.")
        site_url = site_url or input("Jira server URL (https://jira.example.com): ").strip()
        email = email or input("Jira user ID: ").strip()
        projects = projects or input("Project keys (space-separated): ").split()
        reporters = reporters or [entry.strip() for entry in input("Reporter user IDs or names (comma-separated): ").split(",")]
        if arguments.year is None and saved is None:
            year = int(input(f"Report year [{year}]: ").strip() or str(year))
    return Settings(site_url=site_url, email=email, projects=projects, reporters=reporters, year=year)
