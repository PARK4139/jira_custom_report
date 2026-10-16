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
        if not valid_project(project):
            raise RuntimeError('Jira returned an invalid project list.')
        result[project['key']] = {'key': project['key'], 'name': project['name']}
    return sorted(result.values(), key=lambda project: (project['name'].casefold(), project['key']))


def valid_project(project) -> bool:
    return (isinstance(project, dict) and isinstance(project.get('key'), str)
            and re.fullmatch(r'[A-Za-z0-9_-]+', project['key']) is not None
            and isinstance(project.get('name'), str) and bool(project['name'].strip())
            and not any(ord(c) < 32 or ord(c) == 127 for c in project['name']))


def fetch_project(credentials: Credentials, key: str) -> dict:
    """Look up one project by key. Jira's project list can omit projects the account may still query by key."""
    if not isinstance(key, str) or re.fullmatch(r'[A-Za-z0-9_-]{1,50}', key) is None:
        raise ValueError('Invalid project key.')
    auth = base64.b64encode(f'{credentials.email}:{credentials.token}'.encode()).decode()
    request = Request(f'{credentials.url}/rest/api/2/project/{key}',
                      headers={'Authorization': f'Basic {auth}', 'Accept': 'application/json'})
    project = request_json(request, 'project_lookup')
    if not valid_project(project):
        raise RuntimeError('Jira returned an invalid project.')
    return {'key': project['key'], 'name': project['name']}
