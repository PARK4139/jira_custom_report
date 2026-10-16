"""Demo mode: the real dashboard on dummy data, with no Jira connection, login, or change to the real saved inputs."""
import contextlib
from datetime import datetime
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import jira_credentials
import jira_dashboard_server as web
import jira_dashboard_service as service
import jira_demo as demo
import jira_inputs
import jira_issue_monthly
import jira_projects
import jira_reporters
from jira_credentials import Credentials
from jira_periods import PERIODS, period_ranges


def no_jira(*args, **kwargs):
    raise AssertionError("The demo must never send a request to Jira.")


class DemoServerTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.inputs_file = Path(directory.name) / "demo-inputs.json"
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        for module in (jira_issue_monthly, jira_projects, jira_reporters):
            stack.enter_context(patch.object(module, "request_json", side_effect=no_jira))
        stack.enter_context(patch.object(jira_issue_monthly, "build_opener", side_effect=no_jira))
        stack.enter_context(demo.demo_environment(self.inputs_file))
        self.server = web.DashboardServer(Credentials("https://demo.invalid", "demo", "demo-not-a-real-password"),
                                          demo.DEFAULT_PROJECTS, demo.DEFAULT_REPORTERS)
        thread = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=.01), daemon=True)
        thread.start()
        self.addCleanup(self.close_server, thread)

    def close_server(self, thread):
        self.server.shutdown()
        self.server.server_close()
        thread.join(timeout=2)

    def request(self, payload=None, path=None):
        headers = {"Origin": self.server.origin, "X-Session-Token": self.server.session, "Content-Type": "application/json"}
        request = Request(self.server.origin + (path or ("/" if payload is None else "/api/report")),
                          data=None if payload is None else json.dumps(payload).encode(), headers=headers)
        try:
            with urlopen(request, timeout=10) as response:
                return response.status, response.read().decode()
        except HTTPError as error:
            with error:
                return error.code, error.read().decode()

    def test_page_and_project_and_reporter_lists_come_from_dummy_data(self):
        code, page = self.request()
        self.assertEqual(code, 200)
        self.assertIn('id="projects"', page)
        code, body = self.request({}, path="/api/projects")
        projects = json.loads(body)["projects"]
        self.assertEqual((code, len(projects)), (200, 12))
        self.assertEqual({project["key"] for project in projects}, {key for key, _, _ in demo.PROJECTS})
        code, body = self.request({"query": "kim"}, path="/api/reporters")
        self.assertEqual(json.loads(body)["reporters"], [{"name": "kim02", "displayName": "김민수"}])
        self.assertEqual(len(json.loads(self.request({"query": ""}, path="/api/reporters")[1])["reporters"]), 8)
        self.assertEqual(self.request({"key": "ATLAS"}, path="/api/project")[0], 200)
        self.assertEqual(self.request({"key": "NOPE"}, path="/api/project")[0], 404)

    def test_report_covers_every_period_with_plausible_deterministic_numbers(self):
        payload = {"year": 2025, "projects": ["ATLAS", "NOVA"], "reporters": demo.DEFAULT_REPORTERS}
        code, body = self.request(payload)
        self.assertEqual(code, 200)
        result = json.loads(body)
        self.assertEqual(set(result["datasets"]), set(PERIODS))
        self.assertEqual(self.request(payload)[1], body, "the same selection always shows the same numbers")
        for period in PERIODS:
            rows = result["datasets"][period]
            self.assertEqual(len(rows), len(period_ranges(2025, period)))
            created, resolved = sum(row["created"] for row in rows), sum(row["resolved"] for row in rows)
            self.assertGreater(created, 500, period)
            self.assertTrue(0 < resolved <= created * 1.2, (period, created, resolved))
        self.assertEqual([report["key"] for report in result["projectReports"]], ["ATLAS", "NOVA"])
        self.assertEqual(result["queryCount"], 1)

    def test_selected_reporters_filter_the_dummy_issues(self):
        everyone = json.loads(self.request({"year": 2025, "projects": ["ATLAS"], "reporters": demo.DEFAULT_REPORTERS})[1])
        one = json.loads(self.request({"year": 2025, "projects": ["ATLAS"], "reporters": ["hong01"]})[1])
        nobody = json.loads(self.request({"year": 2025, "projects": ["ATLAS"], "reporters": ["not-a-demo-user"]})[1])
        total = lambda result: sum(row["created"] for row in result["datasets"]["yearly"])
        self.assertTrue(0 < total(one) < total(everyone))
        self.assertEqual(total(nobody), 0)

    def test_no_dummy_issue_is_dated_in_the_future(self):
        today = datetime.now(jira_issue_monthly.TZ).date()
        records, _ = demo.fetch_year_issues(["ATLAS", "HELIX"], today.year, demo.DEFAULT_REPORTERS, None)
        self.assertTrue(records)
        self.assertTrue(all(created <= today and (resolved is None or created <= resolved <= today) for _, created, resolved in records))

    def test_inputs_are_saved_to_the_demo_file_only(self):
        real_file = jira_inputs.F_INPUTS
        self.assertEqual(real_file, self.inputs_file, "inside the demo the saved-inputs file is the demo file")
        self.assertEqual(self.request({"values": {"year": "2024", "theme": "dark"}}, path="/api/inputs")[0], 200)
        self.assertEqual(json.loads(self.inputs_file.read_text(encoding="utf-8")), {"year": "2024", "theme": "dark"})
        self.assertIn('"year": "2024"', self.request()[1], "the demo page restores its own saved inputs")


class DemoEnvironmentTests(unittest.TestCase):
    def test_the_real_dashboard_is_untouched_outside_the_demo(self):
        names = [(service, "fetch_year_issues"), (web, "fetch_projects"), (web, "fetch_project"), (web, "search_reporters"), (jira_inputs, "F_INPUTS")]
        before = [getattr(module, name) for module, name in names]
        with demo.demo_environment(Path("demo-inputs-test.json")):
            self.assertIs(service.fetch_year_issues, demo.fetch_year_issues)
            self.assertIs(web.fetch_projects, demo.fetch_projects)
        self.assertEqual([getattr(module, name) for module, name in names], before)
        with self.assertRaises(RuntimeError), demo.demo_environment(Path("demo-inputs-test.json")):
            raise RuntimeError("restore even when the demo fails")
        self.assertEqual([getattr(module, name) for module, name in names], before)

    def test_default_demo_inputs_file_is_not_the_real_one(self):
        with demo.demo_environment():
            self.assertEqual(jira_inputs.F_INPUTS.name, "demo-inputs.json")
            self.assertNotEqual(jira_inputs.F_INPUTS.name, "inputs.json")

    def test_start_up_asks_for_no_login_and_prints_the_demo_notice(self):
        output = io.StringIO()
        with patch("sys.argv", ["jira-demo", "--no-open"]), \
                patch.object(jira_credentials, "prompt_credentials", side_effect=AssertionError("no login prompt in the demo")), \
                patch.object(jira_credentials, "getpass", side_effect=AssertionError("no password prompt in the demo")), \
                patch("builtins.input", side_effect=AssertionError("no prompt in the demo")), \
                patch.object(web.DashboardServer, "serve_forever", side_effect=KeyboardInterrupt), \
                contextlib.redirect_stdout(output):
            demo.main()
        text = output.getvalue()
        self.assertIn("Dashboard (DEMO): http://127.0.0.1:", text)
        self.assertIn("no Jira connection", text)
        self.assertIn("Demo stopped.", text)


if __name__ == "__main__":
    unittest.main()


class DemoBrowserTests(unittest.TestCase):
    @unittest.skipUnless(__import__('shutil').which('node') and Path('C:/Program Files/Google/Chrome/Application/chrome.exe').exists(), 'Node and Chrome are needed')
    def test_real_chrome_opens_the_demo_with_no_login_and_only_contacts_localhost(self):
        import subprocess
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(['node', str(root / 'tests/check_demo_chrome.cjs')], cwd=root,
                                capture_output=True, text=True, encoding='utf-8', timeout=180)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
