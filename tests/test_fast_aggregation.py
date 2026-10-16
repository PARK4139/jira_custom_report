"""Single paged year search: request count, paging, concurrency, failures, and equivalence with per-bucket JQL."""
import contextlib
from datetime import datetime, timedelta, timezone
import io
import math
from pathlib import Path
import random
import re
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import jira_audit
import jira_jql_log
from jira_credentials import Credentials
import jira_dashboard_service as service
import jira_issue_monthly as report
from jira_periods import PERIODS
from jira_settings import Settings
import jira_year_search as search

KST = timezone(timedelta(hours=9))


def stamp(moment: datetime) -> str:
    return moment.strftime('%Y-%m-%dT%H:%M:%S.000%z')


def synthetic_issues(count=2345):
    generator = random.Random(78)
    issues = []
    edge_cases = [
        ('DEMO', '2026-01-01T00:00:00.000+0900', None),
        ('DEMO', '2025-12-31T23:59:59.000+0900', '2026-01-01T00:00:00.000+0900'),
        ('OTHER', '2026-12-31T23:59:00.000+0900', '2027-01-01T00:00:00.000+0900'),
        ('OTHER', '2026-03-31T15:30:00.000+0000', '2026-06-30T15:00:00.000+0000'),
        ('DEMO', '2026-12-31T14:59:59.000+0000', None),
        ('DEMO', '2025-06-01T09:00:00.000+0900', '2025-07-01T09:00:00.000+0900'),
    ]
    for project, created, resolved in edge_cases:
        issues.append({'id': str(len(issues) + 1), 'fields': {'project': {'key': project}, 'created': created, 'resolutiondate': resolved}})
    base = datetime(2025, 10, 1, tzinfo=KST)
    for _ in range(count):
        created = base + timedelta(minutes=generator.randrange(0, 60 * 24 * 500))
        resolved = None if generator.random() < .3 else created + timedelta(minutes=generator.randrange(0, 60 * 24 * 90))
        issues.append({'id': str(len(issues) + 1), 'fields': {'project': {'key': generator.choice(['DEMO', 'OTHER'])},
                                                              'created': stamp(created),
                                                              'resolutiondate': stamp(resolved) if resolved else None}})
    return issues


def kst_date(value):
    return None if value is None else datetime.strptime(value, '%Y-%m-%dT%H:%M:%S.%f%z').astimezone(KST).date().isoformat()


def in_range(issue, field, lower, upper):
    value = kst_date(issue['fields']['created' if field == 'created' else 'resolutiondate'])
    return value is not None and lower <= value < upper


class FakeJira:
    """Search endpoint that evaluates the year JQL over synthetic issues as a KST-profile Jira would."""

    def __init__(self, issues, cap=1000, fail_at=None, delay=0.0):
        self.issues, self.cap, self.fail_at, self.delay = issues, cap, fail_at, delay
        self.calls, self.active, self.peak = [], 0, 0
        self.lock = threading.Lock()

    def __call__(self, request, event, expected_type=dict):
        import json
        payload = json.loads(request.data)
        with self.lock:
            self.calls.append(payload)
            self.active += 1
            self.peak = max(self.peak, self.active)
        try:
            time.sleep(self.delay)
            if payload['startAt'] == self.fail_at:
                raise RuntimeError('Jira HTTP 503: Request rejected; check site and request settings. Redirects are disabled.')
            match = re.fullmatch(r'project IN \((.+?)\) AND reporter IN \(.+?\) AND \(\(created >= "(\S+)" AND created < "(\S+)"\) '
                                 r'OR \(resolved >= "\S+" AND resolved < "\S+"\)\) ORDER BY key ASC', payload['jql'])
            projects = set(json.loads('[' + match.group(1) + ']'))
            lower, upper = match.group(2), match.group(3)
            matched = [issue for issue in self.issues if issue['fields']['project']['key'] in projects
                       and (in_range(issue, 'created', lower, upper) or in_range(issue, 'resolved', lower, upper))]
            size = min(payload['maxResults'], self.cap)
            start = payload['startAt']
            return {'startAt': start, 'maxResults': size, 'total': len(matched), 'issues': matched[start:start + size]}
        finally:
            with self.lock:
                self.active -= 1


class FastAggregationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(jira_audit, 'F_RUNTIME_LOG', root / 'runtime.jsonl'))
        stack.enter_context(patch.object(jira_jql_log, 'F_JQL_LOG', root / 'jql.jsonl'))
        stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.credentials = Credentials('https://jira.internal', 'sample', 'synthetic-secret')
        self.issues = synthetic_issues()
        self.settings = Settings(site_url=self.credentials.url, email=self.credentials.email,
                                 projects=['DEMO', 'OTHER'], reporters=['sample'], year=2026)

    def build(self, fake):
        with patch.object(search, 'request_json', side_effect=fake):
            return service.build_report(self.settings, self.credentials, {})

    def test_one_report_sends_ceil_total_over_page_size_requests(self):
        fake = FakeJira(self.issues)
        result = self.build(fake)
        total = sum(1 for issue in self.issues if in_range(issue, 'created', '2026-01-01', '2027-01-01')
                    or in_range(issue, 'resolved', '2026-01-01', '2027-01-01'))
        self.assertGreater(total, 1000)
        self.assertEqual(len(fake.calls), math.ceil(total / 1000))
        self.assertEqual(result['queryCount'], len(fake.calls))
        self.assertEqual(len({call['jql'] for call in fake.calls}), 1)
        self.assertTrue(all(call['fields'] == ['project', 'created', 'resolutiondate'] for call in fake.calls))
        self.assertEqual(sorted(call['startAt'] for call in fake.calls), list(range(0, total, 1000)))

    def test_lower_server_page_cap_is_honored_without_skipping_issues(self):
        fake = FakeJira(self.issues, cap=250)
        fast = self.build(fake)
        total = fast['datasets']['yearly'][0]
        reference = self.build(FakeJira(self.issues))
        self.assertEqual(fast['datasets'], reference['datasets'])
        self.assertEqual(sorted(call['startAt'] for call in fake.calls)[:3], [0, 250, 500])
        self.assertTrue(all(call['maxResults'] == 250 for call in fake.calls[1:]))
        self.assertGreater(total['created'], 0)

    def test_page_fetches_run_concurrently_with_at_most_eight_workers(self):
        fake = FakeJira(self.issues, cap=100, delay=.02)
        self.build(fake)
        self.assertGreater(len(fake.calls), 9)
        self.assertGreater(fake.peak, 1)
        self.assertLessEqual(fake.peak, search.MAX_WORKERS)

    def test_any_page_failure_fails_the_whole_report(self):
        with self.assertRaisesRegex(RuntimeError, 'Jira HTTP 503'):
            self.build(FakeJira(self.issues, cap=500, fail_at=1000))

    def test_results_changing_between_pages_fail_instead_of_miscounting(self):
        fake = FakeJira(self.issues, cap=500)
        original = fake.__call__

        def shrinking(request, event, expected_type=dict):
            result = original(request, event, expected_type)
            if result['startAt'] == 0:
                fake.issues = fake.issues[:-50]
            return result
        with patch.object(search, 'request_json', side_effect=shrinking), self.assertRaisesRegex(RuntimeError, 'changed during the query'):
            service.build_report(self.settings, self.credentials, {})

    def test_bucket_counts_match_previous_per_bucket_jql_for_every_period_and_project(self):
        fast = self.build(FakeJira(self.issues))

        def per_bucket(url, email, token, jql, **kwargs):
            match = re.fullmatch(r'project = "(\w+)" AND reporter IN \(.+\) AND (created|resolved) >= "(\S+)" AND \2 < "(\S+)"', jql)
            project, field, lower, upper = match.groups()
            return iter([issue for issue in self.issues if issue['fields']['project']['key'] == project
                         and in_range(issue, field, lower, upper)])
        with patch.object(report, 'fetch_issues', side_effect=per_bucket), patch.object(report, 'record_event'):
            for index, project in enumerate(['DEMO', 'OTHER']):
                for period in PERIODS:
                    old = report.collect_period_counts(project, 2026, ['sample'], self.credentials, period)
                    new = fast['projectReports'][index]['datasets'][period]
                    self.assertEqual([(row['created'], row['resolved']) for row in old],
                                     [(row['created'], row['resolved']) for row in new], (project, period))
                    self.assertEqual(old[0].get('carry'), new[0].get('carry'), (project, period, 'carry-over from January 1'))
                    if period in ('q2', 'q3', 'q4'):
                        self.assertGreater(new[0]['carry']['created'], 0, 'the synthetic data has issues before this quarter')
        for period in PERIODS:
            combined = [(row['created'], row['resolved']) for row in fast['datasets'][period]]
            separate = [tuple(a[f] + b[f] for f in ('created', 'resolved'))
                        for a, b in zip(*(project['datasets'][period] for project in fast['projectReports']))]
            self.assertEqual(combined, separate)

    def test_boundary_edge_cases_land_in_the_expected_buckets(self):
        records = [search._issue_record(issue, {'demo': 'DEMO', 'other': 'OTHER'}) for issue in self.issues[:6]]
        monthly = search.count_buckets([record[1:] for record in records], 2026, 'monthly')
        # Jan: 01-01 KST created, 2025 issue resolved 01-01 KST. Apr: UTC 03-31 15:30 is KST 04-01. Jul: UTC 06-30 15:00 resolved is KST 07-01.
        # Dec: 12-31 KST created, and UTC 12-31 14:59 (KST 23:59) created; resolution on 2027-01-01 is excluded.
        self.assertEqual((monthly[0]['created'], monthly[0]['resolved']), (1, 1))
        self.assertEqual((monthly[3]['created'], monthly[6]['resolved']), (1, 1))
        self.assertEqual((monthly[11]['created'], monthly[11]['resolved']), (2, 0))
        self.assertEqual(sum(row['created'] for row in monthly), 4)
        self.assertEqual(sum(row['resolved'] for row in monthly), 2)

    def test_response_shape_and_verification_jql_are_unchanged(self):
        result = self.build(FakeJira(self.issues))
        self.assertEqual(set(result), {'year', 'datasets', 'projectReports', 'queryCount'})
        row = result['projectReports'][0]['datasets']['monthly'][0]
        self.assertEqual(row['queries']['created'],
                         'project = "DEMO" AND reporter IN ("sample") AND created >= "2026-01-01" AND created < "2026-02-01"')
        self.assertEqual(set(row), {'label', 'start', 'end', 'created', 'resolved', 'queries'})


if __name__ == '__main__':
    unittest.main()
