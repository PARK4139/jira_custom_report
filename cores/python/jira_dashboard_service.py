"""Build combined and per-project aggregates independently of the web server."""
from jira_credentials import Credentials
from jira_periods import PERIODS, period_jql
from jira_settings import Settings
from jira_year_search import count_buckets, fetch_year_issues


def build_report(settings: Settings, credentials: Credentials, project_names: dict) -> dict:
    year = settings.year
    projects = list(dict.fromkeys(settings.projects))
    records, request_count = fetch_year_issues(projects, year, settings.reporters, credentials)
    datasets = {}
    project_reports = {key: {'key': key, 'name': project_names.get(key, key), 'datasets': {}} for key in projects}
    for period in PERIODS:
        rows = None
        for project in projects:
            project_rows = count_buckets([record for record in records if record[0] == project], year, period)
            # The JQL text is shown for verification; the counts come from the single search above.
            project_reports[project]['datasets'][period] = [dict(row, queries={field: period_jql(project, settings.reporters, row['start'], row['end'], field)
                                                                            for field in ('created', 'resolved')}) for row in project_rows]
            if rows is None:
                rows = [dict(row, queries={field: [] for field in ('created', 'resolved')}) for row in project_rows]
            else:
                for total, row in zip(rows, project_rows):
                    for field in ('created', 'resolved'):
                        total[field] += row[field]
            for row in rows:
                for field in ('created', 'resolved'):
                    row['queries'][field].append(period_jql(project, settings.reporters, row['start'], row['end'], field))
        for row in rows:
            row['queries'] = {field: '\n\n'.join(queries) for field, queries in row['queries'].items()}
        datasets[period] = rows
    return {'year': year, 'datasets': datasets, 'projectReports': list(project_reports.values()),
            'queryCount': request_count}
