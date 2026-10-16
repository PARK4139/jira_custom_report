"""Saved-report browser dispatch without network, real tokens, or GUI in tests."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError

import jira_audit
import jira_jql_log
import jira_credentials
import jira_issue_monthly as report
from jira_settings import Settings
import launch_report


def issue_response():
    response = Mock()
    response.__enter__ = Mock(return_value=io.BytesIO(json.dumps({"issues": [{"fields": {
        "created": "2026-01-01T00:00:00Z", "resolutiondate": "2026-02-01T00:00:00Z"}}], "startAt": 0, "total": 0}).encode()))
    response.__exit__ = Mock(return_value=False)
    return response


class HtmlPreviewTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.d_root = Path(self.temporary.name)
        self.d_reports = self.d_root / "HTML 결과 # report"
        self.settings = Settings(site_url="https://jira.internal", email="fake@example.com",
            projects=["DEMO", "OTHER"], reporters=["synthetic-reporter"], year=2026)
        credentials = jira_credentials.Credentials(url=self.settings.site_url, email=self.settings.email, token="synthetic-browser-token")
        self.stack = contextlib.ExitStack()
        self.stack.enter_context(patch.object(report, "main", report.export_main))
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch("sys.argv", ["report", "--periods", "monthly", "--output-dir", str(self.d_reports)]))
        self.stack.enter_context(patch.object(report, "load_settings", return_value=self.settings))
        self.stack.enter_context(patch.object(report, "save_settings"))
        self.stack.enter_context(patch.object(report, "prompt_credentials", return_value=credentials))
        self.stack.enter_context(patch.object(report, "save_credentials"))
        self.stack.enter_context(patch.object(report, "delete_credentials"))
        self.stack.enter_context(patch.object(jira_audit, "F_RUNTIME_LOG", self.d_root / "runtime.jsonl"))
        self.stack.enter_context(patch.object(jira_jql_log, "F_JQL_LOG", self.d_root / "jql.jsonl"))
        self.browser = self.stack.enter_context(patch.object(report.webbrowser, "open_new_tab", return_value=True))
        self.opener = Mock()
        self.opener.open.side_effect = lambda *args, **kwargs: issue_response()
        self.stack.enter_context(patch.object(report, "build_opener", return_value=self.opener))
        self.output = self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.errors = self.stack.enter_context(contextlib.redirect_stderr(io.StringIO()))

    def test_default_opens_each_html_only_after_all_files_are_saved(self):
        expected = [self.d_reports / f"{project}_2026_monthly_issues.html" for project in self.settings.projects]

        def observe_saved_files(uri):
            for f_html in expected:
                self.assertTrue(f_html.is_file())
                self.assertTrue(f_html.with_suffix(".csv").is_file())
                self.assertIn("Monthly Issue Trend", f_html.read_text(encoding="utf-8"))
            self.assertIn(uri, [f_html.resolve().as_uri() for f_html in expected])
            return True

        self.browser.side_effect = observe_saved_files
        self.assertEqual(launch_report.execute_report(), 0)
        self.assertEqual([call.args[0] for call in self.browser.call_args_list], [f.resolve().as_uri() for f in expected])
        self.assertIn("%20", self.browser.call_args_list[0].args[0])
        self.assertIn("%23", self.browser.call_args_list[0].args[0])
        self.assertNotIn("synthetic-browser-token", self.output.getvalue())
        runtime = (self.d_root / "runtime.jsonl").read_text(encoding="utf-8")
        self.assertNotIn("synthetic-browser-token", runtime)
        self.assertEqual(sum(json.loads(line).get("outcome") == "dispatched" for line in runtime.splitlines()), 2)

    def test_no_open_saves_reports_without_browser_calls(self):
        with patch("sys.argv", ["report", "--periods", "monthly", "--no-open", "--output-dir", str(self.d_reports)]):
            report.export_main()
        self.browser.assert_not_called()
        self.assertEqual(len(list(self.d_reports.glob("*.html"))), 2)
        self.assertEqual(len(list(self.d_reports.glob("*.csv"))), 2)

    def test_failed_later_project_does_not_open_partial_results(self):
        self.opener.open.side_effect = [*[issue_response() for _ in range(24)], HTTPError("https://api.atlassian.com", 401,
            "Unauthorized", {}, io.BytesIO(b"synthetic-browser-token"))]
        self.assertEqual(launch_report.execute_report(), 1)
        self.assertTrue((self.d_reports / "DEMO_2026_monthly_issues.html").is_file())
        self.browser.assert_not_called()
        self.assertNotIn("synthetic-browser-token", self.errors.getvalue())

    def test_failed_file_save_does_not_open_any_browser(self):
        with patch.object(report, "write_html", side_effect=OSError("Synthetic save failure")):
            self.assertEqual(launch_report.execute_report(), 1)
        self.browser.assert_not_called()

    def test_browser_false_preserves_report_success_and_manual_path(self):
        self.browser.return_value = False
        self.assertEqual(launch_report.execute_report(), 0)
        self.assertEqual(len(list(self.d_reports.glob("*.html"))), 2)
        self.assertIn("open it manually", self.errors.getvalue())
        self.assertIn(str(self.d_reports.resolve()), self.errors.getvalue())

    def test_browser_exception_is_nonfatal_and_redacted(self):
        for error in (OSError("synthetic-browser-token"), report.webbrowser.Error("synthetic-browser-token")):
            self.browser.side_effect = error
            self.assertEqual(launch_report.execute_report(), 0)
        self.assertNotIn("synthetic-browser-token", self.errors.getvalue())
        self.assertTrue((self.d_reports / "DEMO_2026_monthly_issues.html").is_file())

    def test_missing_html_does_not_launch_browser(self):
        self.assertFalse(report.open_html_report(path=self.d_reports / "missing.html"))
        self.browser.assert_not_called()

    def test_management_and_help_paths_do_not_open_browser(self):
        modes = ["--configure", "--save-credentials", "--delete-credentials", "--help"]
        general = ["--site-url", self.settings.site_url, "--email", self.settings.email,
            "--project", "DEMO", "--reporter", "synthetic-reporter", "--year", "2026"]
        for mode in modes:
            with self.subTest(mode=mode), patch("sys.argv", ["report", "--periods", "monthly", mode, *general]):
                self.assertEqual(launch_report.execute_report(), 0)
        self.browser.assert_not_called()
        self.opener.open.assert_not_called()
