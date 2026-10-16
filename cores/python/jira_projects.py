"""Fetch and validate the accessible on-premises Jira project catalog."""
import base64
import re
from urllib.request import Request

from jira_credentials import Credentials
from jira_issue_monthly import request_json


def fetch_projects(credentials: Credentials) -> list[dict]:
    auth = base64.b64encode(f'{credentials.email}:{credentials.token}'.encode()).decode()
    request = Request(credentials.url + '/rest/api/2/project',
                      headers={'Authorization': f'Basic {auth}', 'Accept': 'application/json'})
    projects = request_json(request, 'project_list', expected_type=list)
    result = {}
    for project in projects:
        if (not isinstance(project, dict) or not isinstance(project.get('key'), str)
                or not re.fullmatch(r'[A-Za-z0-9_-]+', project['key'])
                or not isinstance(project.get('name'), str) or not project['name'].strip()
                or any(ord(c) < 32 or ord(c) == 127 for c in project['name'])):
            raise RuntimeError('Jira returned an invalid project list.')
        result[project['key']] = {'key': project['key'], 'name': project['name']}
    return sorted(result.values(), key=lambda project: (project['name'].casefold(), project['key']))
