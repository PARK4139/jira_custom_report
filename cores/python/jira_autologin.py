"""Opt-in auto login: keep the Jira login in Windows Credential Manager so the next launch needs no prompt.

Nothing is saved unless the user turns Auto login on in the dashboard. The login is stored only in Windows
Credential Manager (never in a file, the browser, or a log) under its own entry, separate from the report CLI's
saved passwords, and it is only ever used for the Jira server URL and user ID it was saved with.
"""
from __future__ import annotations

import json
from urllib.parse import urlsplit

from jira_credentials import SERVICE, Credentials, _vault, validate_profile

ENTRY_PREFIX = "dashboard-"


def entry_name(profile: str) -> str:
    validate_profile(profile)
    return validate_profile(ENTRY_PREFIX + profile)


def same_server(first: str, second: str) -> bool:
    """URLs name the same Jira server when scheme, host, port, and path agree (case and a trailing slash do not matter)."""
    def key(url):
        parts = urlsplit(url)
        return parts.scheme.lower(), (parts.hostname or "").lower(), parts.port, parts.path.rstrip("/")
    return key(first) == key(second)


class WindowsAutoLogin:
    available = True

    def __init__(self, profile: str = "default"):
        self.entry = entry_name(profile)

    def enabled(self) -> bool:
        try:
            return _vault().get_password(SERVICE, self.entry) is not None
        except Exception:
            return False

    def load(self, url: str | None = None, user_id: str | None = None) -> Credentials | None:
        """The saved login, or None when there is none, it is unreadable, or it belongs to another server or user."""
        try:
            raw = _vault().get_password(SERVICE, self.entry)
            if raw is None:
                return None
            payload = json.loads(raw)
            credentials = Credentials(payload["url"], payload["email"], payload["token"], allow_insecure_http=payload.get("http") is True)
        except Exception:
            return None
        if (url is not None and not same_server(url, credentials.url)) or (user_id is not None and user_id != credentials.email):
            return None
        return credentials

    def enable(self, credentials: Credentials) -> None:
        payload = {"url": credentials.url, "email": credentials.email, "token": credentials.token}
        if credentials.allow_insecure_http:
            payload["http"] = True
        try:
            _vault().set_password(SERVICE, self.entry, json.dumps(payload))
        except Exception:
            raise RuntimeError("Could not save the login in Windows Credential Manager.") from None

    def disable(self) -> None:
        try:
            vault = _vault()
            if vault.get_password(SERVICE, self.entry) is not None:
                vault.delete_password(SERVICE, self.entry)
        except Exception:
            raise RuntimeError("Could not remove the saved login from Windows Credential Manager.") from None


class MemoryAutoLogin:
    """Same behavior without touching the OS: used by the demo so the button looks and works like the real one."""
    available = True

    def __init__(self):
        self._saved = None

    def enabled(self) -> bool:
        return self._saved is not None

    def load(self, url=None, user_id=None):
        return self._saved

    def enable(self, credentials: Credentials) -> None:
        self._saved = credentials

    def disable(self) -> None:
        self._saved = None


class NoAutoLogin:
    """No store: the dashboard hides the Auto login button."""
    available = False

    def enabled(self) -> bool:
        return False

    def load(self, url=None, user_id=None):
        return None

    def enable(self, credentials) -> None:
        raise RuntimeError("Auto login is not available.")

    def disable(self) -> None:
        pass
