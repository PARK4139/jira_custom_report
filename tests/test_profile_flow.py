"""Controlled first-use/reuse/storage flows; no real Jira or vault access."""
import base64
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import Mock, patch

import jira_audit
import jira_jql_log
import jira_credentials
import jira_issue_monthly as report
import jira_paths
import jira_settings

FAKE_TOKEN = "synthetic-profile-test-secret"


def json_response(payload):
    response = Mock()
    response.__enter__ = Mock(side_effect=lambda: io.BytesIO(json.dumps(payload).encode()))
    response.__exit__ = Mock(return_value=False)
    return response


class ProfileFlowTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.d_root = Path(self.temporary.name)
        self.d_local = self.d_root / "local"
        self.d_reports = self.d_root / "reports"
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(jira_paths, "D_LOCAL", self.d_local))
        self.stack.enter_context(patch.object(jira_audit, "F_RUNTIME_LOG", self.d_local / "runtime.jsonl"))
        self.stack.enter_context(patch.object(jira_jql_log, "F_JQL_LOG", self.d_local / "jql.jsonl"))
        self.stack.enter_context(patch.object(sys.stdin, "isatty", return_value=True))
        self.vault = self.stack.enter_context(patch.object(jira_credentials, "_vault"))
        self.settings = jira_settings.Settings(site_url="https://jira.internal", email="fake@example.com",
            projects=["DEMO"], reporters=["reporter-one"], year=2026)

    def run_report(self, arguments=None, opener=None):
        if opener is None:
            opener = Mock()
            opener.open.return_value = json_response({"issues": [], "startAt": 0, "total": 0})
        with patch.object(sys, "argv", ["report", "--periods", "monthly", "--no-open", "--output-dir", str(self.d_reports), *(arguments or [])]), \
                patch.object(report, "build_opener", return_value=opener), contextlib.redirect_stdout(io.StringIO()):
            report.export_main()
        return opener

    def test_first_run_saves_only_general_settings_and_generates_report(self):
        opener = Mock()
        opener.open.side_effect = [ json_response({"issues": [
            {"fields": {"created": "2026-01-01T00:00:00Z", "resolutiondate": None}}], "startAt": 0, "total": 0}),
            *[json_response({"issues": [], "startAt": 0, "total": 0}) for _ in range(23)]]
        answers = ["https://jira.internal", "fake@example.com", "DEMO", "reporter-one, reporter-two", "2026"]
        with patch("builtins.input", side_effect=answers), patch.object(jira_credentials, "getpass", return_value=FAKE_TOKEN) as prompt:
            self.run_report(opener=opener)
        profile = self.d_local / "default.toml"
        payload = tomllib.loads(profile.read_text(encoding="utf-8"))
        self.assertEqual(set(payload["jira"]), {"site_url", "email"})
        self.assertEqual(payload["report"]["reporters"], ["reporter-one", "reporter-two"])
        self.assertIn("01,1,0", (self.d_reports / "DEMO_2026_monthly_issues.csv").read_text(encoding="utf-8-sig"))
        prompt.assert_called_once()
        self.vault.assert_not_called()
        encoded_auth = base64.b64encode(f"fake@example.com:{FAKE_TOKEN}".encode()).decode()
        for f_output in self.d_root.rglob("*"):
            if f_output.is_file():
                content = f_output.read_text(encoding="utf-8-sig")
                self.assertNotIn(FAKE_TOKEN, content)
                self.assertNotIn(encoded_auth, content)
        requests = [call.args[0] for call in opener.open.call_args_list]
        self.assertEqual(requests[0].full_url, self.settings.site_url + "/rest/api/2/search")

    def test_repeat_runs_prompt_only_for_token_even_with_a_saved_vault(self):
        jira_settings.save_settings(profile="default", settings=self.settings)
        with patch("builtins.input", side_effect=AssertionError("General settings must be reused")), \
                patch.object(jira_credentials, "getpass", return_value=FAKE_TOKEN) as prompt:
            for _ in range(2):
                opener = self.run_report()
                self.assertEqual(opener.open.call_count, 24)
            self.assertEqual(prompt.call_count, 2)
        self.vault.assert_not_called()

    def test_restarted_process_reuses_toml_and_still_prompts_for_token(self):
        jira_settings.save_settings(profile="default", settings=self.settings)
        program = '''
import io, json, sys
from pathlib import Path
from unittest.mock import Mock, patch
import jira_audit, jira_credentials, jira_jql_log, jira_paths
import jira_issue_monthly as report
jira_paths.D_LOCAL = Path(sys.argv[1])
jira_audit.F_RUNTIME_LOG = jira_paths.D_LOCAL / 'restart.jsonl'
jira_jql_log.F_JQL_LOG = jira_paths.D_LOCAL / 'restart-jql.jsonl'
response = Mock()
response.__enter__ = Mock(side_effect=lambda: io.BytesIO(json.dumps({'issues': [], 'startAt': 0, 'total': 0}).encode()))
response.__exit__ = Mock(return_value=False)
opener = Mock()
opener.open.return_value = response
sys.argv = ['report', '--periods', 'monthly', '--no-open', '--output-dir', sys.argv[2]]
with patch.object(sys.stdin, 'isatty', return_value=True), patch('builtins.input', side_effect=AssertionError('Unexpected general prompt')), patch.object(jira_credentials, 'getpass', return_value='synthetic-restart-secret') as prompt, patch.object(jira_credentials, '_vault', side_effect=AssertionError('Vault accessed')), patch.object(report, 'build_opener', return_value=opener):
    report.export_main()
    assert prompt.call_count == 1
    assert opener.open.call_count == 24
'''
        result = subprocess.run([sys.executable, "-X", "utf8", "-c", program, str(self.d_local), str(self.d_reports)],
            cwd=jira_paths.D_PROJECT, stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.d_reports / "DEMO_2026_monthly_issues.html").exists())
        self.assertNotIn("synthetic-restart-secret", result.stdout + result.stderr)

    def test_configure_never_requests_or_saves_token(self):
        arguments = ["--configure", "--url", self.settings.site_url, "--id", self.settings.email,
            "--project", "DEMO", "--reporter", "reporter-one", "--year", "2026"]
        with patch.object(jira_credentials, "getpass", side_effect=AssertionError("Token requested")):
            opener = self.run_report(arguments=arguments)
        self.vault.assert_not_called()
        opener.open.assert_not_called()
        self.assertEqual(jira_settings.load_settings(profile="default"), self.settings)

    def test_explicit_save_use_delete_and_default_prompt_are_independent(self):
        jira_settings.save_settings(profile="default", settings=self.settings)
        store = {}
        backend = self.vault.return_value
        backend.set_password.side_effect = lambda service, profile, payload: store.update({(service, profile): payload})
        backend.get_password.side_effect = lambda service, profile: store.get((service, profile))
        backend.delete_password.side_effect = lambda service, profile: store.pop((service, profile))
        with patch.object(jira_credentials, "getpass", return_value=FAKE_TOKEN) as prompt:
            self.run_report(arguments=["--save-credentials"])
            prompt.assert_called_once()
        self.assertEqual(len(store), 1)
        backend.get_password.assert_not_called()
        with patch.object(jira_credentials, "getpass", side_effect=AssertionError("Unexpected token prompt")):
            self.run_report(arguments=["--use-saved-credentials"])
        backend.get_password.assert_called_once()
        backend.reset_mock()
        with patch.object(jira_credentials, "getpass", return_value="another-synthetic-token"):
            self.run_report()
        backend.get_password.assert_not_called()
        backend.set_password.assert_not_called()
        self.run_report(arguments=["--delete-credentials"])
        self.assertFalse(store)
        self.assertTrue((self.d_local / "default.toml").exists())
        with self.assertRaisesRegex(RuntimeError, "No saved password"):
            self.run_report(arguments=["--use-saved-credentials"])

    def test_saved_account_mismatch_is_rejected_before_api_call(self):
        jira_settings.save_settings(profile="default", settings=self.settings)
        self.vault.return_value.get_password.return_value = json.dumps({"url": self.settings.site_url,
            "email": "different@example.com", "token": FAKE_TOKEN})
        opener = Mock()
        with self.assertRaisesRegex(RuntimeError, "do not match"):
            self.run_report(arguments=["--use-saved-credentials"], opener=opener)
        opener.open.assert_not_called()

    def test_secret_field_and_corrupt_toml_fail_without_echoing_content(self):
        jira_settings.save_settings(profile="default", settings=self.settings)
        profile = self.d_local / "default.toml"
        valid = profile.read_text(encoding="utf-8")
        for content in ('token = "synthetic-invalid-secret"\n' + valid, 'broken = "synthetic-invalid-secret'):
            profile.write_text(content, encoding="utf-8")
            with self.subTest(content=content), self.assertRaises(RuntimeError) as error:
                jira_settings.load_settings(profile="default")
            self.assertNotIn("synthetic-invalid-secret", str(error.exception))

    def test_configure_can_repair_corrupt_profile_without_reading_secrets(self):
        self.d_local.mkdir()
        (self.d_local / "default.toml").write_text('token = "synthetic-invalid-secret"', encoding="utf-8")
        self.run_report(arguments=["--configure", "--site-url", self.settings.site_url, "--email", self.settings.email,
            "--project", "DEMO", "--reporter", "reporter-one", "--year", "2026"])
        self.assertEqual(jira_settings.load_settings(profile="default"), self.settings)
        self.vault.assert_not_called()

    def test_site_override_uses_server_without_cloud_discovery(self):
        arguments = Mock(site_url="https://another.internal", email=None, project=None, reporter=None, year=None)
        completed = jira_settings.complete_settings(arguments=arguments, saved=self.settings)
        self.assertFalse(hasattr(completed, "cloud_id"))
        self.assertEqual(completed.site_url, "https://another.internal")

    def test_general_settings_roundtrip_uses_real_toml_escaping(self):
        settings = jira_settings.Settings(site_url=self.settings.site_url, email=self.settings.email,
            projects=["DEMO"], reporters=['reporter "quoted" # name'], year=2026)
        jira_settings.save_settings(profile="quotes", settings=settings)
        self.assertEqual(jira_settings.load_settings(profile="quotes"), settings)

    def test_token_cli_argument_is_rejected(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            self.run_report(arguments=["--token", FAKE_TOKEN])
        self.assertEqual(error.exception.code, 2)
        self.vault.assert_not_called()
