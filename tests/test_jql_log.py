"""Native JQL log: exact query text, paging, no credentials."""
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import jira_jql_log
import jira_issue_monthly as report


class JqlLogTests(unittest.TestCase):
    def test_fetch_issues_logs_each_page_with_exact_jql(self):
        jql = 'project = "DEMO" AND reporter IN ("김철수") AND created >= "2026-01-01"'
        pages = [{"issues": [{"fields": {}}], "total": 2, "startAt": 0},
                 {"issues": [{"fields": {}}], "total": 2, "startAt": 1}]
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "logs" / "jql.jsonl"
            with patch.object(jira_jql_log, "F_JQL_LOG", log), \
                    patch.object(report, "request_json", side_effect=pages):
                list(report.fetch_issues("https://jira.internal", "user", "synthetic-jql-token", jql))
            text = log.read_text(encoding="utf-8")
        entries = [json.loads(line) for line in text.splitlines()]
        self.assertEqual([(e["jql"], e["start_at"], e["total"]) for e in entries], [(jql, 0, 2), (jql, 1, 2)])
        self.assertIn("김철수", text)
        self.assertNotIn("synthetic-jql-token", text)

    def test_unwritable_log_does_not_break_the_report(self):
        with tempfile.TemporaryDirectory() as directory:
            blocker = Path(directory) / "logs"
            blocker.write_text("not a directory")
            with patch.object(jira_jql_log, "F_JQL_LOG", blocker / "jql.jsonl"):
                jira_jql_log.log_jql("project = DEMO", 0)


if __name__ == "__main__":
    unittest.main()
