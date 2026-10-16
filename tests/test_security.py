import io
import json
from email.message import Message
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import HTTPSHandler, ProxyHandler, Request, build_opener
from urllib.response import addinfourl

import jira_credentials as credentials
import jira_issue_monthly as report
import jira_audit
import jira_jql_log
from jira_settings import Settings


_JQL_LOG_DIR = tempfile.TemporaryDirectory()
_JQL_LOG_PATCH = patch.object(jira_jql_log, "F_JQL_LOG", Path(_JQL_LOG_DIR.name) / "jql.jsonl")


def setUpModule():
    _JQL_LOG_PATCH.start()


def tearDownModule():
    _JQL_LOG_PATCH.stop()
    _JQL_LOG_DIR.cleanup()



def json_response(payload):
    response = Mock()
    response.__enter__ = Mock(side_effect=lambda: io.BytesIO(json.dumps(payload).encode()))
    response.__exit__ = Mock(return_value=False)
    return response


class CredentialTests(unittest.TestCase):
    def test_https_server_urls_are_validated(self):
        invalid = ["http://example.atlassian.net", "https://u:p@example.com", "https://:@example.com",
                   "https://jira.internal?token=secret",
                   "https://jira.internal#fragment",
                   "https://jira.internal:bad", "https://jira.internal\n", "https://jira.internal\\other"]
        for url in invalid:
            with self.subTest(url=url), self.assertRaises(ValueError):
                credentials.validate_url(url)
        self.assertEqual(credentials.validate_url("https://jira.internal/"), "https://jira.internal")

    def test_secrets_are_not_in_repr(self):
        value = credentials.Credentials("https://jira.internal", "fake@example.com", "fake-secret")
        self.assertNotIn("fake-secret", repr(value))
        self.assertNotIn("fake@example.com", repr(value))

    def test_header_control_characters_are_rejected(self):
        for email, token in [("fake\n@example.com", "fake"), ("fake@example.com", "fake\r\nheader")]:
            with self.assertRaises(ValueError):
                credentials.Credentials("https://jira.internal", email, token)

    def test_vault_round_trip_and_delete_use_profile(self):
        vault = Mock()
        value = credentials.Credentials("https://jira.internal", "fake@example.com", "fake-secret")
        with patch.object(credentials, "_vault", return_value=vault):
            credentials.save_credentials("work", value)
            service, profile, payload = vault.set_password.call_args.args
            self.assertEqual((service, profile), (credentials.SERVICE, "work"))
            vault.get_password.return_value = payload
            self.assertEqual(credentials.load_credentials("work"), value)
            credentials.delete_credentials("work")
            vault.delete_password.assert_called_once_with(credentials.SERVICE, "work")

    def test_missing_or_corrupt_credentials_fail_closed(self):
        vault = Mock()
        with patch.object(credentials, "_vault", return_value=vault):
            for raw in (None, "not-json", "[]", "null", json.dumps({"url": "http://example.atlassian.net"})):
                vault.get_password.return_value = raw
                with self.subTest(raw=raw), self.assertRaises(RuntimeError):
                    credentials.load_credentials("default")

    def test_vault_errors_do_not_expose_secrets(self):
        vault = Mock()
        vault.get_password.side_effect = RuntimeError("fake-secret")
        with patch.object(credentials, "_vault", return_value=vault):
            with self.assertRaises(RuntimeError) as result:
                credentials.load_credentials("default")
        self.assertNotIn("fake-secret", str(result.exception))

    def test_bad_profile_is_rejected_before_vault_access(self):
        with patch.object(credentials, "_vault") as vault:
            for profile in ("../bad", "CON", "nul", "LPT1", "com9.profile", ".", ".."):
                with self.subTest(profile=profile), self.assertRaises(ValueError):
                    credentials.load_credentials(profile=profile)
            vault.assert_not_called()

    def test_non_windows_has_no_file_fallback(self):
        with patch.object(credentials.sys, "platform", "linux"):
            with self.assertRaisesRegex(RuntimeError, "Windows"):
                credentials._vault()

    @unittest.skipUnless(credentials.sys.platform == "win32", "Windows native backend")
    def test_native_backend_uses_local_persistence(self):
        with patch("keyring.backends.Windows.WinVaultKeyring") as backend:
            vault = credentials._vault()
            self.assertIs(vault, backend.return_value)
            self.assertEqual(vault.persist, "local machine")

    def test_prompt_refuses_visible_getpass_fallback(self):
        def visible_fallback(*args):
            import warnings
            warnings.warn("hidden input unavailable", credentials.GetPassWarning)

        with patch.object(credentials.sys.stdin, "isatty", return_value=True), \
                patch("builtins.input", side_effect=["https://jira.internal", "fake@example.com"]), \
                patch.object(credentials, "getpass", side_effect=visible_fallback):
            with self.assertRaisesRegex(RuntimeError, "terminal"):
                credentials.prompt_credentials()

    def test_prompt_rejects_piped_credentials(self):
        with patch.object(credentials.sys.stdin, "isatty", return_value=False):
            with self.assertRaises(RuntimeError):
                credentials.prompt_credentials()


class TransportTests(unittest.TestCase):
    def test_server_basic_auth_context_path_and_offset_pagination(self):
        opener = Mock()
        opener.open.side_effect = [
            json_response({"issues": [{"fields": {}}], "startAt": 0, "total": 2}),
            json_response({"issues": [{"fields": {}}], "startAt": 1, "total": 2})]
        with patch.object(report, "build_opener", return_value=opener):
            issues = list(report.fetch_issues(url="https://jira.internal:8443/jira", email="alice", token="fake-secret", jql="query"))
        requests = [call.args[0] for call in opener.open.call_args_list]
        self.assertEqual(len(issues), 2)
        import base64
        for request in requests:
            self.assertEqual(request.full_url, "https://jira.internal:8443/jira/rest/api/2/search")
            self.assertEqual(request.get_header("Authorization"), "Basic " + base64.b64encode(b"alice:fake-secret").decode())
            self.assertEqual(json.loads(request.data)["fields"], ["created", "resolutiondate"])
        self.assertEqual([json.loads(r.data)["startAt"] for r in requests], [0, 1])

    def test_unsafe_server_urls_fail_before_auth(self):
        with patch.object(report, "build_opener") as opener:
            for url in ("http://jira.internal", "https://u:p@jira.internal", "https://jira.internal/jira?pw=x", "https://jira.internal/../other", "https://jira.internal/%2e%2e"):
                with self.subTest(url=url), self.assertRaises(ValueError):
                    list(report.fetch_issues(url=url, email="fake", token="fake-secret", jql="query"))
            opener.assert_not_called()

    def test_nonadvancing_pagination_is_rejected(self):
        for page in ({"issues": [], "startAt": 0, "total": 2},
                     {"issues": [{"fields": {}}], "startAt": 1, "total": 2}):
            opener = Mock()
            opener.open.return_value = json_response(page)
            with patch.object(report, "build_opener", return_value=opener), self.assertRaisesRegex(RuntimeError, "pagination"):
                list(report.fetch_issues(url="https://jira.internal", email="fake", token="fake-secret", jql="query"))

    def test_invalid_search_response_is_not_an_empty_success(self):
        for payload in ({}, {"issues": [], "isLast": "true"}, {"issues": [None], "startAt": 0, "total": 1}):
            opener = Mock()
            opener.open.return_value = json_response(payload)
            with self.subTest(payload=payload), patch.object(report, "build_opener", return_value=opener), self.assertRaises(RuntimeError):
                list(report.fetch_issues(url="https://jira.internal", email="fake", token="fake-secret", jql="query"))

    def test_audit_log_has_no_secret_headers_or_query(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "runtime.jsonl"
            opener = Mock()
            opener.open.return_value = json_response({"issues": [], "startAt": 0, "total": 0})
            with patch.object(jira_audit, "F_RUNTIME_LOG", log), patch.object(jira_jql_log, "F_JQL_LOG", log.with_name("jql.jsonl")), patch.object(report, "build_opener", return_value=opener):
                list(report.fetch_issues(url="https://jira.internal", email="private@example.com", token="fake-secret", jql="private-jql"))
            logged = log.read_text(encoding="utf-8")
            for secret in ("fake-secret", "private@example.com", "private-jql", "Authorization", "Basic "):
                self.assertNotIn(secret, logged)
            self.assertTrue(all(json.loads(line)["run_id"] for line in logged.splitlines()))

    def test_redirect_never_reaches_second_host(self):
        calls = []

        class FakeHTTPS(HTTPSHandler):
            def https_open(self, request):
                calls.append(request.full_url)
                headers = Message()
                headers["Location"] = "https://other.example.com/steal"
                response = addinfourl(io.BytesIO(b""), headers, request.full_url, 302)
                response.msg = "Found"
                return response

        opener = build_opener(report.NoRedirect(), ProxyHandler({}), FakeHTTPS())
        with self.assertRaises(HTTPError):
            opener.open(Request("https://jira.internal/start", headers={"Authorization": "Basic fake"}))
        self.assertEqual(calls, ["https://jira.internal/start"])

    def test_http_error_body_is_not_logged(self):
        opener = Mock()
        opener.open.side_effect = HTTPError("https://jira.internal", 401, "Unauthorized", {},
                                            io.BytesIO(b"fake-secret and internal issue details"))
        with patch.object(report, "build_opener", return_value=opener):
            with self.assertRaises(RuntimeError) as result:
                list(report.fetch_issues("https://jira.internal", "fake@example.com", "fake-secret", "query"))
        self.assertIn("401", str(result.exception))
        self.assertNotIn("fake-secret", str(result.exception))
        self.assertNotIn("internal issue", str(result.exception))

    def test_http_is_rejected_before_request(self):
        with patch.object(report, "build_opener") as opener:
            with self.assertRaises(ValueError):
                list(report.fetch_issues("http://example.atlassian.net", "fake@example.com", "fake-secret", "query"))
            opener.assert_not_called()


class ReportTests(unittest.TestCase):
    def test_server_report_end_to_end(self):
        value = credentials.Credentials("https://jira.internal", "fake@example.com", "fake-secret")
        opener = Mock()
        opener.open.side_effect = [
            json_response({"issues": [{"fields": {"created": "2026-01-01T00:00:00Z", "resolutiondate": None}}], "startAt": 0, "total": 0}),
            *[json_response({"issues": [], "startAt": 0, "total": 0}) for _ in range(23)]]
        with tempfile.TemporaryDirectory() as directory, \
                patch("sys.argv", ["report", "--periods", "monthly", "--no-open", "--year", "2026", "--site-url", "https://jira.internal", "--email", "fake@example.com", "--project", "DEMO", "--reporter", "fake", "--output-dir", directory]), \
                patch.object(report, "load_settings", return_value=None), patch.object(report, "save_settings"), \
                patch.object(report, "prompt_credentials", return_value=value), \
                patch.object(report, "build_opener", return_value=opener), patch("builtins.print"):
            report.export_main()
            self.assertIn("01,1,0", (Path(directory) / "DEMO_2026_monthly_issues.csv").read_text(encoding="utf-8-sig"))
            self.assertIn("DEMO", (Path(directory) / "DEMO_2026_monthly_issues.html").read_text(encoding="utf-8"))
            self.assertEqual(opener.open.call_count, 24)

    def test_reporter_jql_escapes_quotes(self):
        name = 'reporter" OR project = "OTHER'
        jql = report.build_monthly_jql(project="DEMO", year=2026, reporters=[name], month=1, date_field="created")
        self.assertIn(json.dumps(name), jql)

    def test_mocked_report_keeps_counts_and_escapes_reporter(self):
        rows = [{"month": f"{month:02d}", "created": int(month == 1), "resolved": int(month == 2)} for month in range(1, 13)]
        with tempfile.TemporaryDirectory() as directory:
            html = Path(directory) / "report.html"
            csv = Path(directory) / "report.csv"
            report.write_html(html, "DEMO", 2026, rows, ["<script>fake</script>"])
            report.write_csv(path=csv, rows=rows)
            self.assertIn("&lt;script&gt;fake&lt;/script&gt;", html.read_text(encoding="utf-8"))
            self.assertNotIn("<script>fake</script>", html.read_text(encoding="utf-8"))
            self.assertIn("01,1,0", csv.read_text(encoding="utf-8-sig"))

    def test_env_secrets_do_not_override_default_hidden_prompt(self):
        value = credentials.Credentials("https://jira.internal", "fake@example.com", "prompt-token")
        settings = Settings(site_url=value.url, email=value.email, projects=["DEMO"], reporters=["fake"], year=2026)
        with tempfile.TemporaryDirectory() as directory, \
                patch.dict("os.environ", {"JIRA_API_TOKEN": "env-token", "JIRA_URL": "http://bad.example.com"}), \
                patch("sys.argv", ["report", "--periods", "monthly", "--no-open", "--project", "DEMO", "--reporter", "fake", "--output-dir", directory]), \
                patch.object(report, "load_settings", return_value=settings), \
                patch.object(report, "load_credentials") as load, patch.object(report, "save_credentials") as save, \
                patch.object(report, "prompt_credentials", return_value=value) as prompt, \
                patch.object(report, "fetch_issues", return_value=iter([])) as fetch, \
                patch("builtins.print"):
            report.export_main()
            load.assert_not_called()
            save.assert_not_called()
            prompt.assert_called_once_with(url=value.url, email=value.email)
            self.assertEqual(fetch.call_args.kwargs["token"], "prompt-token")


if __name__ == "__main__":
    unittest.main()
