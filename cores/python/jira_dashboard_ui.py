"""Compose dashboard HTML with packaged frontend assets and escaped config."""
import json
import re

from cores.html import read_asset
from jira_periods import PERIODS
from jira_report_view import render_html


def dashboard_html(session: str, project: str, reporters: list[str], current_year: int, saved: dict | None = None,
                   auto_login: dict | None = None) -> str:
    html = render_html("Jira", current_year, [], [], {period: [] for period in PERIODS})
    html = html.replace('const datasets=', 'let datasets=')
    html = html.replace('<h1>Jira', '<h1 id="report-title">Jira')
    html = html.replace('<div class="sub">Created / Resolved by reporting period. Reporters: </div>', '')
    html = html.replace(f'<footer>{current_year} calendar year.', f'<footer><span id="selected-year">{current_year}</span> calendar year.')
    controls = read_asset("query-form.html")
    html = html.replace('<nav class="tabs"', controls + '<nav class="tabs"', 1)
    html = html.replace('<div class="chart-wrap">', '<div id="combined-chart" class="chart-wrap">', 1)
    html = html.replace('<div class="table-scroll">', '<div id="combined-table" class="table-scroll">', 1)
    html = html.replace('</section>', '<div id="project-graphs"></div></section>', 1)
    html = html.replace('<p id="period-note">', '<button type="button" id="download-csv">Download CSV</button><p id="period-note">', 1)
    html = html.replace('</style>', read_asset("dashboard.css") + "</style>")
    config = json.dumps(dict(session=session, project=project, reporters=reporters, currentYear=current_year, saved=saved or {},
                                 autoLogin=auto_login or {'available': False, 'enabled': False}))
    config = config.replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    script = (read_asset("combo.js") + read_asset("dashboard.js") + read_asset("project-charts.js")).replace('WEB_CONFIG', config)
    return arrange_layout(enhance_dashboard(html.replace('</script>', script + '</script>', 1)))


def enhance_dashboard(html: str) -> str:
    html = html.replace('<body>', '<body>' + read_asset("preferences.html"), 1)
    html = html.replace('<div class="eyebrow">SQA · ISSUE MANAGEMENT</div>', '', 1)
    html = html.replace('<nav class="tabs"', read_asset("period-selector.html") + '<nav class="tabs"', 1)
    html = html.replace('<button type="button" id="download-csv">Download CSV</button>',
                        '<div class="exports"><button type="button" id="download-csv">Download CSV</button>'
                        '<button type="button" id="download-jpg">Export JPG</button></div>', 1)
    return html.replace('</script>', (read_asset("locales.js") + read_asset("preferences.js") + read_asset("exports.js")) + '</script>', 1)


def arrange_layout(html: str) -> str:
    """Separate the page into a Jira-style top bar, a controls sidebar, and a graphs area."""
    preferences = re.search(r'<div class="preferences">.*?</div>\s*', html, re.S)
    heading = re.search(r'<h1 id="report-title">.*?</h1>\s*', html, re.S)
    controls = re.search(r'<form id="query-form">.*?(?=<nav class="tabs")', html, re.S)
    graphs = re.search(r'<nav class="tabs".*?</section>\s*', html, re.S)
    parts = (preferences, heading, controls, graphs)
    if not all(parts):
        return html
    start, end = min(m.start() for m in parts), max(m.end() for m in parts)
    layout = (
        '<header class="topbar"><span class="brand">Jira</span>'
        f'<div class="titles">{heading.group().strip()}</div>{preferences.group().strip()}</header>\n'
        '<div class="layout"><aside class="controls" aria-labelledby="controls-heading">'
        '<h2 id="controls-heading" data-text="controlsHeading">Filters</h2>'
        f'{controls.group().strip()}</aside>\n'
        f'<main class="graphs" aria-labelledby="period-heading">{graphs.group().strip()}</main></div>\n')
    page = html[:start] + layout + html[end:]
    # Explanatory notes (period note + footer text) live together at the very bottom of the page.
    page = page.replace('<p id="period-note"></p>', '', 1)
    return page.replace('<footer>', '<footer><p id="period-note" hidden></p><p id="footer-text">', 1).replace('</footer>', '</p></footer>', 1)
