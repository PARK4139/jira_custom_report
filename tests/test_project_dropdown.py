import base64
import io
import json
import unittest
from unittest.mock import Mock, patch

from jira_credentials import Credentials
import jira_issue_monthly as report
import jira_projects as web


class ProjectListTests(unittest.TestCase):
    def test_on_prem_project_list_preserves_keys_and_returns_only_names(self):
        credentials = Credentials('https://jira.internal:8443/jira', 'sample', 'synthetic-secret')
        payload = [{'key': 'B', 'name': 'Zulu', 'lead': {'emailAddress': 'private@example.com'}},
                   {'key': 'A', 'name': 'Alpha <script>'}]
        response = Mock()
        response.__enter__ = Mock(return_value=io.BytesIO(json.dumps(payload).encode()))
        response.__exit__ = Mock(return_value=False)
        opener = Mock()
        opener.open.return_value = response
        with patch.object(report, 'build_opener', return_value=opener), patch.object(report, 'record_event'):
            projects = web.fetch_projects(credentials)
        self.assertEqual(projects, [{'key': 'A', 'name': 'Alpha <script>'}, {'key': 'B', 'name': 'Zulu'}])
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, 'https://jira.internal:8443/jira/rest/api/2/project')
        self.assertEqual(request.get_method(), 'GET')
        self.assertEqual(request.get_header('Authorization'), 'Basic ' + base64.b64encode(b'sample:synthetic-secret').decode())

    def test_invalid_project_entries_fail_instead_of_offering_bad_jql_keys(self):
        credentials = Credentials('https://jira.internal', 'sample', 'synthetic-secret')
        for projects in ([{}], [{'key': 'A" OR project=B', 'name': 'Bad'}], [{'key': 'A', 'name': ''}], [None]):
            with self.subTest(projects=projects), patch.object(web, 'request_json', return_value=projects), self.assertRaises(RuntimeError):
                web.fetch_projects(credentials)


class ReporterSearchTests(unittest.TestCase):
    def search(self, users, query):
        import jira_reporters
        credentials = Credentials('https://jira.internal:8443/jira', 'sample', 'synthetic-secret')
        response = Mock()
        response.__enter__ = Mock(return_value=io.BytesIO(json.dumps(users).encode()))
        response.__exit__ = Mock(return_value=False)
        opener = Mock()
        opener.open.return_value = response
        with patch.object(report, 'build_opener', return_value=opener), patch.object(report, 'record_event'):
            result = jira_reporters.search_reporters(credentials, query)
        return result, opener.open.call_args.args[0]

    def test_search_sends_only_the_partial_name_and_returns_names_without_private_fields(self):
        users = [{'name': 'b', 'displayName': 'Zed', 'emailAddress': 'private@example.com'},
                 {'name': 'a', 'displayName': 'Amy'}, {'name': 'c'}]
        result, request = self.search(users, ' 박정 ')
        self.assertEqual(result, [{'name': 'a', 'displayName': 'Amy'}, {'name': 'c', 'displayName': 'c'},
                                  {'name': 'b', 'displayName': 'Zed'}])
        self.assertEqual(request.full_url, 'https://jira.internal:8443/jira/rest/api/2/user/search?username=%EB%B0%95%EC%A0%95&includeInactive=false&maxResults=50')
        self.assertEqual(request.get_method(), 'GET')
        self.assertEqual(request.get_header('Authorization'), 'Basic ' + base64.b64encode(b'sample:synthetic-secret').decode())

    def test_empty_query_lists_first_users_and_injection_attempts_are_url_encoded(self):
        self.assertIn('username=.&', self.search([], '')[1].full_url)
        url = self.search([], 'a&maxResults=1000#x')[1].full_url
        self.assertIn('username=a%26maxResults%3D1000%23x&', url)
        self.assertEqual(url.count('&maxResults='), 1, 'injected parameters stay inside the encoded username value')
        self.assertNotIn('#', url)

    def test_invalid_queries_and_user_entries_are_rejected(self):
        import jira_reporters
        credentials = Credentials('https://jira.internal', 'sample', 'synthetic-secret')
        for query in ('x' * 101, 'a\nb', None, 5):
            with self.subTest(query=query), self.assertRaises(ValueError):
                jira_reporters.search_reporters(credentials, query)
        for users in ([{}], [{'name': ''}], [{'name': 'a\x00'}], [None]):
            with self.subTest(users=users), patch.object(jira_reporters, 'request_json', return_value=users), self.assertRaises(RuntimeError):
                jira_reporters.search_reporters(credentials, 'a')
