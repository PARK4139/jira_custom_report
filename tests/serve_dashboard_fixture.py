"""Local-only synthetic dashboard for browser checks; no Jira requests."""
from unittest.mock import patch
import argparse
from jira_credentials import Credentials
from datetime import date, timedelta
import jira_dashboard_server
import jira_inputs
from jira_web import DashboardServer
from pathlib import Path


USERS = [{"name": "sample", "displayName": "Sample User"}, {"name": "fail", "displayName": "Fail User"},
         {"name": "parkjh", "displayName": "박정훈"}, {"name": "kimsh", "displayName": "김선희"}]


def search_users(credentials, query):
    needle = query.strip().casefold()
    return [user for user in USERS if needle in user["name"].casefold() or needle in user["displayName"].casefold()]


def collect(projects, year, reporters, credentials):
    if reporters == ["fail"]:
        raise RuntimeError("Synthetic query failure")
    start = date(year, 1, 1)
    records = [(project, start + timedelta(days=day), start + timedelta(days=day + 3) if day % 3 else None)
               for project in projects for day in range(0, 360, 2)]
    return records, 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=0)
    args = parser.parse_args()
    output_dir = Path('.local/ui-verification/fixture-outputs').resolve()
    inputs_file = Path('.local/ui-verification/fixture-inputs.json').resolve()
    with patch.object(jira_inputs, "F_INPUTS", inputs_file), patch("jira_dashboard_server.D_OUTPUTS", output_dir), patch(
            "jira_dashboard_service.fetch_year_issues", side_effect=collect), patch(
            "jira_dashboard_server.fetch_projects", return_value=[
                {"key": "DEMO", "name": "Demo team"}, {"key": "HTG", "name": "Hotel group"},
                {"key": "OTHER", "name": "Platform team"}]), patch(
            "jira_dashboard_server.search_reporters", side_effect=search_users), DashboardServer(
            Credentials("https://jira.invalid", "synthetic-user", "synthetic-secret"),
            ["DEMO"], ["sample"], port=args.port) as server:
        print(server.origin, flush=True)
        server.serve_forever()
