"""Exercise the real loopback HTTP boundary with synthetic Jira responses."""
import contextlib
import io
import json
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from datetime import date

from jira_credentials import Credentials
from jira_periods import PERIODS, period_ranges
import jira_issue_monthly as report
import jira_dashboard_server as web
import jira_dashboard_service as service
import jira_dashboard_cli as cli


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.credentials = Credentials('https://jira.internal/jira', 'sample-user', 'synthetic-server-secret')
        self.server = web.DashboardServer(self.credentials, ['DEMO'], ['sample-reporter'])
        self.thread = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=.01), daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(self, payload=None, path=None, **headers):
        defaults = {'Origin': self.server.origin, 'X-Session-Token': self.server.session,
                    'Content-Type': 'application/json'}
        defaults.update(headers)
        request = Request(self.server.origin + (path or ('/' if payload is None else '/api/report')),
                          data=None if payload is None else json.dumps(payload).encode(), headers=defaults)
        try:
            with urlopen(request, timeout=5) as response:
                return response.status, response.headers, response.read().decode()
        except HTTPError as error:
            with error:
                return error.code, error.headers, error.read().decode()

    def test_page_has_year_dropdown_and_no_password_or_network_before_query(self):
        with patch.object(service, 'fetch_year_issues') as collect:
            code, headers, page = self.request()
        self.assertEqual(code, 200)
        self.assertIn('<select id="year"', page)
        self.assertIn('<input id="projects" name="project_name"', page)
        self.assertIn("yearSelect.addEventListener('change'", page)
        self.assertNotIn(self.credentials.token, page)
        self.assertNotIn(self.credentials.email, page)
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertIn("frame-ancestors 'none'", headers['Content-Security-Policy'])
        collect.assert_not_called()

    def test_project_dropdown_endpoint_requires_session_and_returns_names_and_keys(self):
        projects = [{'key': 'DEMO', 'name': 'Quality team'}]
        with patch.object(web, 'fetch_projects', return_value=projects) as fetch:
            code, _, body = self.request({}, path='/api/projects')
            self.assertEqual(code, 200)
            self.assertEqual(json.loads(body), {'projects': projects})
            fetch.assert_called_once_with(self.server.credentials)
            self.assertNotIn(self.credentials.token, body)
            self.assertEqual(self.request({}, path='/api/projects', **{'X-Session-Token': 'bad'})[0], 403)
            self.assertEqual(fetch.call_count, 1)

    def test_project_list_failure_is_retryable_and_does_not_expose_raw_errors(self):
        with patch.object(web, 'fetch_projects', side_effect=OSError(self.credentials.token)):
            code, _, body = self.request({}, path='/api/projects')
        self.assertEqual(code, 500)
        self.assertNotIn(self.credentials.token, body)
        with patch.object(web, 'fetch_projects', return_value=[]):
            self.assertEqual(json.loads(self.request({}, path='/api/projects')[2]), {'projects': []})

    def test_reporter_search_endpoint_requires_session_validates_query_and_hides_raw_errors(self):
        users = [{'name': 'parkjh', 'displayName': 'Park'}]
        with patch.object(web, 'search_reporters', return_value=users) as search:
            code, _, body = self.request({'query': 'par'}, path='/api/reporters')
            self.assertEqual((code, json.loads(body)), (200, {'reporters': users}))
            search.assert_called_once_with(self.server.credentials, 'par')
            self.assertNotIn(self.credentials.token, body)
            self.assertEqual(self.request({'query': 'par'}, path='/api/reporters', **{'X-Session-Token': 'bad'})[0], 403)
            for payload in ({}, {'query': 'a', 'extra': 1}, []):
                self.assertEqual(self.request(payload, path='/api/reporters')[0], 400)
            self.assertEqual(search.call_count, 1)
        with patch.object(web, 'search_reporters', side_effect=ValueError('invalid')):
            self.assertEqual(self.request({'query': 'x' * 101}, path='/api/reporters')[0], 400)
        with patch.object(web, 'search_reporters', side_effect=OSError(self.credentials.token)):
            code, _, body = self.request({'query': 'par'}, path='/api/reporters')
        self.assertEqual(code, 500)
        self.assertNotIn(self.credentials.token, body)

    def test_year_change_queries_correct_jql_for_every_period_and_combines_projects(self):
        def collect(projects, year, reporters, credentials):
            self.assertEqual(projects, ['DEMO', 'OTHER'])
            records = [(project, date(year, 1, 1), date(year, 1, 2)) for project in projects for _ in range(year - 2020)]
            return records, 3

        with patch.object(service, 'fetch_year_issues', side_effect=collect) as query:
            for year in (2024, 2025):
                code, _, body = self.request({'year': year, 'projects': ['DEMO', 'OTHER', 'DEMO'], 'reporters': ['sample']})
                self.assertEqual(code, 200)
                result = json.loads(body)
                self.assertEqual(result['year'], year)
                self.assertEqual(result['queryCount'], 3)
                self.assertEqual(set(result['datasets']), set(PERIODS))
                for period, rows in result['datasets'].items():
                    self.assertEqual(len(rows), len(period_ranges(year, period)))
                    self.assertEqual((rows[0]['created'], rows[0]['resolved']), ((year-2020)*2, (year-2020)*2))
                    self.assertTrue(all(r['created'] == r['resolved'] == 0 for r in rows[1:]))
                    self.assertIn(f'created >= "{year}-01-01"', rows[0]['queries']['created'])
                    self.assertIn('project = "DEMO"', rows[0]['queries']['created'])
                    self.assertIn('project = "OTHER"', rows[0]['queries']['created'])
                self.assertNotIn(self.credentials.token, body)
            self.assertEqual(query.call_count, 2)

    def test_untrusted_requests_and_invalid_year_are_rejected_before_jira(self):
        valid = {'year': 2024, 'projects': ['DEMO'], 'reporters': ['sample']}
        with patch.object(service, 'fetch_year_issues') as query:
            for headers in ({'Origin': 'https://evil.example'}, {'X-Session-Token': 'wrong'}, {'Host': 'evil.example'}):
                self.assertEqual(self.request(valid, **headers)[0], 403)
            for year in (True, '2024', 1969, self.server.current_year+2):
                self.assertEqual(self.request(dict(valid, year=year))[0], 400)
            self.assertEqual(self.request(dict(valid, projects=['DEMO" OR project = OTHER']))[0], 400)
            query.assert_not_called()

    def test_separate_project_graph_data_keeps_names_counts_and_jql_distinct(self):
        self.server.project_names = {'DEMO': 'Quality team', 'OTHER': 'Platform team'}
        def collect(projects, year, reporters, credentials):
            counts = {'DEMO': (2, 1), 'OTHER': (7, 3)}
            records = [(project, date(year, 1, 1), date(year, 1, 1) if index < counts[project][1] else None)
                       for project in projects for index in range(counts[project][0])]
            return records, 1
        with patch.object(service, 'fetch_year_issues', side_effect=collect):
            code, _, body = self.request({'year': 2024, 'projects': ['DEMO', 'OTHER'], 'reporters': ['sample']})
        self.assertEqual(code, 200)
        data = json.loads(body)
        first, second = data['projectReports']
        self.assertEqual((first['name'], second['name']), ('Quality team', 'Platform team'))
        for period in PERIODS:
            self.assertEqual(first['datasets'][period][0]['created'], 2)
            self.assertEqual(second['datasets'][period][0]['created'], 7)
            self.assertEqual(data['datasets'][period][0]['created'], 9)
            self.assertIn('project = "DEMO"', first['datasets'][period][0]['queries']['created'])
            self.assertNotIn('OTHER', first['datasets'][period][0]['queries']['created'])
            self.assertIn('project = "OTHER"', second['datasets'][period][0]['queries']['created'])

    def test_busy_and_failed_queries_do_not_leave_server_locked(self):
        payload = {'year': 2024, 'projects': ['DEMO'], 'reporters': ['sample']}
        self.server.query_lock.acquire()
        try:
            self.assertEqual(self.request(payload)[0], 409)
        finally:
            self.server.query_lock.release()
        with patch.object(service, 'fetch_year_issues', side_effect=OSError('synthetic-server-secret')):
            code, _, body = self.request(payload)
        self.assertEqual(code, 500)
        self.assertNotIn(self.credentials.token, body)
        self.assertFalse(self.server.query_lock.locked())

    def test_web_entry_rejects_year_cli_before_prompting_for_credentials(self):
        with patch('sys.argv', ['report', '--year', '2026']), \
                patch.object(cli, 'prompt_credentials') as prompt, \
                contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            report.main()
        self.assertEqual(error.exception.code, 2)
        prompt.assert_not_called()


if __name__ == '__main__':
    unittest.main()
