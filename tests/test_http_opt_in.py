"""HTTP must be explicit and propagate through the dashboard query boundary."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import jira_credentials as credentials
import jira_jql_log
import jira_issue_monthly as report
import jira_dashboard_cli as web
import test_web_dashboard


_JQL_LOG_DIR = tempfile.TemporaryDirectory()
_JQL_LOG_PATCH = patch.object(jira_jql_log, 'F_JQL_LOG', Path(_JQL_LOG_DIR.name) / 'jql.jsonl')


def setUpModule():
    _JQL_LOG_PATCH.start()


def tearDownModule():
    _JQL_LOG_PATCH.stop()
    _JQL_LOG_DIR.cleanup()


class HttpOptInTests(unittest.TestCase):
    def test_http_url_is_accepted_without_the_extra_flag(self):
        with patch.object(credentials.sys.stdin, 'isatty', return_value=True), patch.object(credentials, 'getpass', return_value='synthetic-secret'), contextlib.redirect_stderr(io.StringIO()) as warning:
            value = credentials.prompt_credentials('http://jira.internal', 'sample')
        self.assertTrue(value.allow_insecure_http)
        self.assertIn('without encryption', warning.getvalue())

    def test_cli_http_url_without_flag_reaches_server_startup(self):
        with patch('sys.argv', ['report', '--url', 'http://jira.internal', '--id', 'sample', '--no-open']), patch.object(web, 'load_settings', return_value=None), patch.object(credentials.sys.stdin, 'isatty', return_value=True), patch.object(credentials, 'getpass', return_value='synthetic-secret'), patch.object(web, 'restarting_dashboard') as restart, contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            web.main()
        self.assertTrue(restart.call_args.args[1].allow_insecure_http)
        self.assertEqual(restart.call_args.args[1].url, 'http://jira.internal')

    def test_warning_precedes_password_and_has_no_secret(self):
        output = io.StringIO()
        def password(*args):
            self.assertIn('without encryption', output.getvalue())
            return 'synthetic-secret'
        with patch.object(credentials.sys.stdin, 'isatty', return_value=True), patch.object(credentials, 'getpass', side_effect=password), contextlib.redirect_stderr(output):
            value = credentials.prompt_credentials('http://jira.internal/jira', 'sample', allow_insecure_http=True)
        self.assertTrue(value.allow_insecure_http)
        self.assertNotIn(value.token, output.getvalue())
        with self.assertRaises(ValueError):
            credentials.Credentials(value.url, value.email, value.token)

    def test_opt_in_preserves_other_url_restrictions(self):
        for url in ['http://u:p@jira.internal', 'http://jira.internal/../other', 'http://jira.internal?pw=x', 'http://jira.internal/%2e', 'ftp://jira.internal', 'https://[bad']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                credentials.validate_url(url, allow_insecure_http=True)

    def test_monthly_and_period_queries_propagate_opt_in_to_transport(self):
        value = credentials.Credentials('http://jira.internal/jira', 'sample', 'synthetic-secret', allow_insecure_http=True)
        opener = Mock()
        response = Mock()
        response.__enter__ = Mock(side_effect=lambda: io.BytesIO(json.dumps({'issues': [], 'total': 0, 'startAt': 0}).encode()))
        response.__exit__ = Mock(return_value=False)
        opener.open.return_value = response
        with patch.object(report, 'build_opener', return_value=opener), patch('builtins.print'):
            self.assertEqual(len(report.collect_monthly_counts('DEMO', 2026, ['sample'], value)), 12)
            self.assertEqual(len(report.collect_period_counts('DEMO', 2026, ['sample'], value, 'yearly')), 1)
        self.assertEqual(opener.open.call_count, 26)
        self.assertTrue(all(c.args[0].full_url == value.url + '/rest/api/2/search' for c in opener.open.call_args_list))

    def test_cli_passes_explicit_opt_in(self):
        with patch('sys.argv', ['report', '--url', 'http://jira.internal', '--id', 'sample', '--allow-insecure-http']), patch.object(web, 'load_settings', return_value=None), patch.object(web, 'prompt_credentials', side_effect=RuntimeError('stop before binding')) as prompt:
            with self.assertRaisesRegex(RuntimeError, 'stop before binding'):
                web.main()
        prompt.assert_called_once_with('http://jira.internal', 'sample', allow_insecure_http=True)


class HttpDashboardTests(test_web_dashboard.DashboardTests):
    def setUp(self):
        super().setUp()
        self.server.credentials = credentials.Credentials('http://jira.internal/jira', 'sample', 'synthetic-secret', allow_insecure_http=True)


if __name__ == '__main__':
    unittest.main()
