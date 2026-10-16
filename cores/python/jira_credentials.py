"""Local credentials: Windows Credential Manager or an ephemeral terminal prompt."""
from __future__ import annotations

from dataclasses import dataclass
from getpass import GetPassWarning, getpass
import json
import re
import sys
from urllib.parse import urlsplit
import warnings

SERVICE = "jira-custom-report"


def validate_url(url: str, *, allow_insecure_http: bool = False) -> str:
    if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in url):
        raise ValueError("Jira URL must not contain whitespace or control characters.")
    parts = None
    try:
        parts = urlsplit(url)
        valid = ((parts.scheme == "https" or (allow_insecure_http and parts.scheme == "http")) and parts.hostname and
                 re.fullmatch(r"[A-Za-z0-9.:-]+", parts.hostname)
                 and parts.username is None
                 and parts.password is None and "\\" not in url and (parts.port is None or 1 <= parts.port <= 65535)
                 and not any(segment in (".", "..") for segment in parts.path.split("/"))
                 and "%" not in parts.path and not parts.query and not parts.fragment)
    except ValueError:
        valid = False
    if parts is not None and parts.scheme == "http" and not allow_insecure_http:
        raise ValueError("HTTP Jira requires --allow-insecure-http; user ID and password would be sent without encryption.")
    if not valid:
        raise ValueError("Enter an HTTPS Jira server base URL, optionally with a port and context path.")
    return url.rstrip("/")


@dataclass(frozen=True, repr=False)
class Credentials:
    url: str
    email: str
    token: str
    allow_insecure_http: bool = False

    def __post_init__(self):
        if not all(isinstance(v, str) and v.strip() for v in (self.url, self.email, self.token)):
            raise ValueError("Jira URL, user ID, and password are required.")
        object.__setattr__(self, "url", validate_url(self.url, allow_insecure_http=self.allow_insecure_http))
        if any(ord(c) < 32 or ord(c) == 127 for c in self.email + self.token) or ":" in self.email:
            raise ValueError("Invalid user ID or password format.")


def validate_profile(profile: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", profile):
        raise ValueError("프로필은 영숫자, _, ., -로 된 1~64자여야 합니다.")
    reserved = {"con", "prn", "aux", "nul", *(f"com{n}" for n in range(1, 10)), *(f"lpt{n}" for n in range(1, 10))}
    if profile in (".", "..") or profile.split(".", 1)[0].lower() in reserved:
        raise ValueError("Profile name cannot be a Windows reserved filename.")
    return profile


def _vault():
    if sys.platform != "win32":
        raise RuntimeError("Credential storage requires Windows. Run without a storage flag to enter a password for one run.")
    try:
        # Instantiate the native backend directly: never select a plaintext/plugin backend.
        from keyring.backends.Windows import WinVaultKeyring
        vault = WinVaultKeyring()
        vault.persist = "local machine"
        return vault
    except Exception:
        raise RuntimeError("Cannot open Windows Credential Manager. Run uv sync and check the native backend.") from None


def prompt_credentials(url: str | None = None, email: str | None = None, *, allow_insecure_http: bool = False) -> Credentials:
    if not sys.stdin.isatty():
        raise RuntimeError("Enter credentials in an interactive terminal; piped password input is disabled.")
    url = url if url is not None else input("Jira server URL (http:// or https://): ").strip()
    allow_insecure_http = allow_insecure_http or urlsplit(url).scheme.lower() == "http"
    url = validate_url(url=url, allow_insecure_http=allow_insecure_http)
    if urlsplit(url).scheme == "http":
        print("경고: HTTP 연결은 Jira 사용자 ID와 비밀번호를 암호화 없이 전송합니다.", file=sys.stderr)
    email = email if email is not None else input("Jira user ID: ").strip()
    # getpass must fail rather than fall back to visible input.
    with warnings.catch_warnings():
        warnings.simplefilter("error", GetPassWarning)
        try:
            token = getpass("Jira password (hidden, not saved by default): ")
        except GetPassWarning:
            raise RuntimeError("A terminal that supports hidden password input is required.") from None
    return Credentials(url, email, token, allow_insecure_http=allow_insecure_http)


def save_credentials(profile: str, credentials: Credentials):
    validate_profile(profile)
    vault = _vault()
    payload = json.dumps({"url": credentials.url, "email": credentials.email, "token": credentials.token})
    try:
        vault.set_password(SERVICE, profile, payload)
    except Exception:
        raise RuntimeError("자격 증명을 저장하지 못했습니다. Windows 자격 증명 관리자를 확인하세요.") from None


def load_credentials(profile: str) -> Credentials:
    validate_profile(profile)
    vault = _vault()
    try:
        raw = vault.get_password(SERVICE, profile)
    except Exception:
        raise RuntimeError("Windows 자격 증명을 읽지 못했습니다.") from None
    if raw is None:
        raise RuntimeError("No saved password. Run normally for hidden input or use --save-credentials to register one.")
    try:
        payload = json.loads(raw)
        return Credentials(payload["url"], payload["email"], payload["token"])
    except (ValueError, KeyError, TypeError):
        raise RuntimeError("Saved credentials are invalid. Use --save-credentials to replace them.") from None


def delete_credentials(profile: str):
    validate_profile(profile)
    vault = _vault()
    try:
        if vault.get_password(SERVICE, profile) is not None:
            vault.delete_password(SERVICE, profile)
    except Exception:
        raise RuntimeError("Windows 자격 증명을 삭제하지 못했습니다.") from None
