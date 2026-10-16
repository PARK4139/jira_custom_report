"""Period coverage, independent queries, exports, and safe offline report data."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import jira_audit
import jira_issue_monthly as report
from jira_credentials import Credentials
from datetime import date, timedelta
from jira_periods import BASE_PERIODS, PERIODS, QUARTERS, period_ranges
from jira_settings import Settings


class QuarterRangeTests(unittest.TestCase):
    def test_each_quarter_is_covered_by_weekly_buckets_without_gaps_or_overlaps(self):
        for year in (2024, 2026):
            for number, period in enumerate(QUARTERS, start=1):
                with self.subTest(year=year, period=period):
                    rows = period_ranges(year, period)
                    quarter_start = date(year, 3 * number - 2, 1)
                    quarter_end = date(year + 1, 1, 1) if number == 4 else date(year, 3 * number + 1, 1)
                    self.assertEqual(rows[0]['start'], str(quarter_start))
                    self.assertEqual(rows[-1]['end'], str(quarter_end))
                    self.assertTrue(all(a['end'] == b['start'] for a, b in zip(rows, rows[1:])))
                    self.assertTrue(all(date.fromisoformat(r['end']) - date.fromisoformat(r['start']) <= timedelta(days=7) for r in rows))
                    self.assertEqual(len(rows), -(-(quarter_end - quarter_start).days // 7))
        self.assertEqual([len(period_ranges(2026, q)) for q in QUARTERS], [13, 13, 14, 14])
        self.assertEqual(period_ranges(2026, 'q3')[0]['label'], '07/01')

    def test_unknown_periods_are_rejected(self):
        for period in ('q0', 'q5', 'quarterly', 'Q1', ''):
            with self.subTest(period=period), self.assertRaises(ValueError):
                period_ranges(2026, period)


class PeriodReportTests(unittest.TestCase):
    def test_calendar_coverage_without_gaps_or_overlaps_including_leap_year(self):
        for year in (2024, 2026):
            for period, expected in zip(PERIODS, (53, 27, 12, 1)):
                with self.subTest(year=year, period=period):
                    rows = period_ranges(year, period)
                    self.assertEqual(len(rows), expected)
                    self.assertEqual(rows[0]["start"], f"{year}-01-01")
                    self.assertEqual(rows[-1]["end"], f"{year+1}-01-01")
                    self.assertTrue(all(a["end"] == b["start"] for a, b in zip(rows, rows[1:])))
        self.assertEqual(period_ranges(2024, "monthly")[1]["end"], "2024-03-01")
        self.assertEqual(period_ranges(2026, "2week")[0]["end"], "2026-01-15")

    def test_default_cli_queries_all_four_periods_and_embeds_real_counts_and_jql(self):
        credentials = Credentials("https://jira.internal:8443/jira", "tester", "synthetic-private-password")
        settings = Settings(credentials.url, credentials.email, ["DEMO"], ['reporter </script><script>alert(1)</script>'], 2026)
        queries = []

        def fetch(*args, **kwargs):
            query = kwargs.get("jql", args[3] if len(args) > 3 else None)
            queries.append(query)
            # Different Created/Resolved counts ensure the UI data isn't fabricated.
            return iter({"fields": {}} for _ in range(2 if "AND created >=" in query else 1))

        with tempfile.TemporaryDirectory() as directory, \
                patch("sys.argv", ["report", "--no-open", "--output-dir", directory]), \
                patch.object(report, "load_settings", return_value=settings), \
                patch.object(report, "prompt_credentials", return_value=credentials), \
                patch.object(report, "fetch_issues", side_effect=fetch), \
                patch.object(jira_audit, "F_RUNTIME_LOG", Path(directory) / "runtime.jsonl"), \
                contextlib.redirect_stdout(io.StringIO()):
            report.export_main()
            self.assertEqual(len(queries), 186)
            self.assertIn('AND created >= "2026-01-01" AND created < "2026-01-08"', queries[0])
            self.assertTrue(any('AND resolved >= "2026-01-01" AND resolved < "2027-01-01"' in q for q in queries))
            html = (Path(directory) / "DEMO_2026_monthly_issues.html").read_text(encoding="utf-8")
            data = json.loads(html.split("const datasets=", 1)[1].split(";\n", 1)[0])
            self.assertEqual(set(data), set(BASE_PERIODS))
            for period, rows in data.items():
                self.assertEqual(len(rows), len(period_ranges(2026, period)))
                self.assertTrue(all((r["created"], r["resolved"]) == (2, 1) for r in rows))
                self.assertTrue(all(r["queries"]["created"] in queries for r in rows))
            self.assertNotIn("</script><script>alert(1)</script>", html)
            self.assertEqual(len(list(Path(directory).glob("*.csv"))), 4)
            self.assertNotIn(credentials.token, html)
            self.assertNotIn(credentials.token, (Path(directory) / "runtime.jsonl").read_text())


if __name__ == "__main__":
    unittest.main()
