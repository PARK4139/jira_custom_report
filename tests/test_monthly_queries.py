"""The 24-query contract and count-to-report agreement with synthetic identities."""
import contextlib
import csv
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import jira_audit
import jira_jql_log
from jira_credentials import Credentials
import jira_issue_monthly as report
from jira_settings import Settings

BOUNDARIES = [
    ("2026-01-01", "2026-02-01"), ("2026-02-01", "2026-03-01"),
    ("2026-03-01", "2026-04-01"), ("2026-04-01", "2026-05-01"),
    ("2026-05-01", "2026-06-01"), ("2026-06-01", "2026-07-01"),
    ("2026-07-01", "2026-08-01"), ("2026-08-01", "2026-09-01"),
    ("2026-09-01", "2026-10-01"), ("2026-10-01", "2026-11-01"),
    ("2026-11-01", "2026-12-01"), ("2026-12-01", "2027-01-01"),
]


class MonthlyQueryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.d_root = Path(self.temporary.name)
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(jira_audit, "F_RUNTIME_LOG", self.d_root / "runtime.jsonl"))
        self.stack.enter_context(patch.object(jira_jql_log, "F_JQL_LOG", self.d_root / "jql.jsonl"))
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.credentials = Credentials(url="https://jira.internal", email="fake@example.com", token="synthetic-monthly-token")
        self.reporters = ["Reporter A", "Reporter B"]

    def collect(self, year=2026):
        return report.collect_monthly_counts(project="DEMO", year=year, reporters=self.reporters,
            credentials=self.credentials)

    def test_all_24_queries_match_independent_month_boundaries_and_saved_counts(self):
        expected = [f'project = "DEMO" AND reporter IN ("Reporter A", "Reporter B") AND {field} >= "{lower}" AND {field} < "{upper}"'
            for field in ("created", "resolved") for lower, upper in BOUNDARIES]
        created = [3, 0, 5, 2, 1, 0, 7, 1, 4, 0, 0, 0]
        resolved = [1, 4, 0, 2, 2, 1, 0, 5, 0, 2, 0, 0]
        query_counts = dict(zip(expected, created + resolved))

        def query_result(**arguments):
            self.assertIn(arguments["jql"], query_counts)
            return iter({"fields": {}} for _ in range(query_counts[arguments["jql"]]))

        settings = Settings(site_url=self.credentials.url, email=self.credentials.email, projects=["DEMO"],
            reporters=self.reporters, year=2026)
        with patch("sys.argv", ["report", "--periods", "monthly", "--no-open", "--output-dir", str(self.d_root)]), \
                patch.object(report, "load_settings", return_value=settings), \
                patch.object(report, "prompt_credentials", return_value=self.credentials), \
                patch.object(report, "fetch_issues", side_effect=query_result) as query, \
                patch.object(report.webbrowser, "open_new_tab") as browser:
            report.export_main()
        self.assertEqual([call.kwargs["jql"] for call in query.call_args_list], expected)
        browser.assert_not_called()
        with (self.d_root / "DEMO_2026_monthly_issues.csv").open(encoding="utf-8-sig", newline="") as stream:
            csv_rows = list(csv.DictReader(stream))
        html = (self.d_root / "DEMO_2026_monthly_issues.html").read_text(encoding="utf-8")
        html_rows = json.loads(html.split("const values=", 1)[1].split(";", 1)[0])
        for index, (csv_row, html_row) in enumerate(zip(csv_rows, html_rows)):
            self.assertEqual((int(csv_row["created"]), int(csv_row["resolved"])), (created[index], resolved[index]))
            self.assertEqual((html_row["created"], html_row["resolved"]), (created[index], resolved[index]))
        self.assertEqual(len(csv_rows), 12)
        self.assertEqual(len(html_rows), 12)
        events = [json.loads(line) for line in (self.d_root / "runtime.jsonl").read_text(encoding="utf-8").splitlines()]
        monthly = [event for event in events if event["event"] == "monthly_query"]
        self.assertEqual([event["count"] for event in monthly], created + resolved)
        self.assertNotIn("synthetic-monthly-token", (self.d_root / "runtime.jsonl").read_text(encoding="utf-8"))

    def test_pagination_counts_every_issue_for_each_month(self):
        requests = []

        def respond(request, timeout):
            payload = json.loads(request.data)
            requests.append(payload)
            first_month = 'created >= "2026-01-01"' in payload["jql"]
            if first_month and payload["startAt"] == 0:
                result = {"issues": [{"fields": {}} for _ in range(100)], "startAt": 0, "total": 107}
            elif first_month:
                self.assertEqual(payload["startAt"], 100)
                result = {"issues": [{"fields": {}} for _ in range(7)], "startAt": 100, "total": 107}
            else:
                result = {"issues": [], "startAt": 0, "total": 0}
            response = Mock()
            response.__enter__ = Mock(return_value=io.BytesIO(json.dumps(result).encode()))
            response.__exit__ = Mock(return_value=False)
            return response

        opener = Mock()
        opener.open.side_effect = respond
        with patch.object(report, "build_opener", return_value=opener):
            rows = self.collect()
        self.assertEqual(rows[0]["created"], 107)
        self.assertEqual(sum(row["resolved"] for row in rows), 0)
        self.assertEqual(len(requests), 25)
        self.assertEqual(len({request["jql"] for request in requests}), 24)

    def test_resolved_count_includes_issues_created_before_the_report_year(self):
        def respond(**arguments):
            if 'resolved >= "2026-01-01"' in arguments["jql"]:
                return iter([{"fields": {"created": "2019-01-01T00:00:00Z", "resolutiondate": "2026-01-05T00:00:00Z"}}])
            return iter([])
        with patch.object(report, "fetch_issues", side_effect=respond):
            rows = self.collect()
        self.assertEqual(rows[0]["created"], 0)
        self.assertEqual(rows[0]["resolved"], 1)

    def test_future_month_zero_results_are_saved_as_zero(self):
        with patch.object(report, "fetch_issues", side_effect=lambda **arguments: iter([])) as query:
            rows = self.collect(year=2099)
        self.assertEqual(query.call_count, 24)
        report.write_csv(path=self.d_root / "future.csv", rows=rows)
        report.write_html(path=self.d_root / "future.html", project="DEMO", year=2099, counts=rows, reporters=self.reporters)
        self.assertIn("12,0,0", (self.d_root / "future.csv").read_text(encoding="utf-8-sig"))
        chart = (self.d_root / "future.html").read_text(encoding="utf-8").split("const values=", 1)[1].split(";", 1)[0]
        self.assertTrue(all(row["created"] == row["resolved"] == 0 for row in json.loads(chart)))

    def test_calendar_boundaries_and_field_validation(self):
        leap = report.build_monthly_jql(project="DEMO", year=2024, reporters=self.reporters, month=2, date_field="created")
        self.assertIn('created >= "2024-02-01" AND created < "2024-03-01"', leap)
        december = report.build_monthly_jql(project="DEMO", year=2026, reporters=self.reporters, month=12, date_field="resolved")
        self.assertIn('resolved >= "2026-12-01" AND resolved < "2027-01-01"', december)
        for month, field in ((0, "created"), (13, "resolved"), (1, "created OR resolved")):
            with self.subTest(month=month, field=field), self.assertRaises(ValueError):
                report.build_monthly_jql(project="DEMO", year=2026, reporters=self.reporters, month=month, date_field=field)
