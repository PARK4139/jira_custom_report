"""Look up active on-premises Jira users that match a partial reporter name."""
import base64
from urllib.parse import urlencode
from urllib.request import Request

from jira_credentials import Credentials
from jira_issue_monthly import request_json

MAX_CANDIDATES = 50
MAX_QUERY_LENGTH = 100


def clean_text(value) -> bool:
    return isinstance(value, str) and bool(value.strip()) and not any(ord(c) < 32 or ord(c) == 127 for c in value)


def search_reporters(credentials: Credentials, query: str) -> list[dict]:
    """Return {name, displayName} for active users matching `query`; an empty query lists the first users."""
    if not isinstance(query, str) or len(query) > MAX_QUERY_LENGTH or any(ord(c) < 32 or ord(c) == 127 for c in query):
        raise ValueError('Invalid reporter query.')
    auth = base64.b64encode(f'{credentials.email}:{credentials.token}'.encode()).decode()
    parameters = urlencode({'username': query.strip() or '.', 'includeInactive': 'false', 'maxResults': MAX_CANDIDATES})
    request = Request(f'{credentials.url}/rest/api/2/user/search?{parameters}',
                      headers={'Authorization': f'Basic {auth}', 'Accept': 'application/json'})
    users = request_json(request, 'reporter_search', expected_type=list)
    result = {}
    for user in users:
        if not isinstance(user, dict) or not clean_text(user.get('name')):
            raise RuntimeError('Jira returned an invalid user list.')
        display = user.get('displayName')
        result[user['name']] = {'name': user['name'], 'displayName': display if clean_text(display) else user['name']}
    return sorted(result.values(), key=lambda user: (user['displayName'].casefold(), user['name']))[:MAX_CANDIDATES]
