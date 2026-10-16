"""Aggregate-only offline report rendering, independent of HTTP and CLI."""
from datetime import datetime
from html import escape
import json
from zoneinfo import ZoneInfo

from cores.html import read_asset
from jira_periods import period_ranges, period_jql

TZ = ZoneInfo("Asia/Seoul")


def render_html(project: str, year: int, counts: list[dict], reporters: list[str], periods: dict | None = None) -> str:
    now = datetime.now(TZ)
    created = sum(x["created"] for x in counts)
    resolved = sum(x["resolved"] for x in counts)
    graph_rows = [
        {"month": x["month"], "created": x["created"], "resolved": x["resolved"]}
        for x in counts
    ]
    # Serialize aggregate numbers only; no issue identifiers/descriptions.
    data = json.dumps(graph_rows, ensure_ascii=False)
    if periods is None:
        periods = {"monthly": [dict(bucket, created=row["created"], resolved=row["resolved"])
                               for bucket, row in zip(period_ranges(year, "monthly"), counts)]}
    period_data = {}
    for period, rows in periods.items():
        period_data[period] = [dict(row, queries={field: period_jql(project, reporters, row["start"], row["end"], field)
                                                for field in ("created", "resolved")}) for row in rows]
    # Script data may include reporter names: prevent closing the script element.
    period_json = json.dumps(period_data, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    project_label = escape(project)
    created_txt = f"{created:,}"
    resolved_txt = f"{resolved:,}"
    ratio_txt = f"{(resolved / created * 100):.1f}%" if created else "—"
    generated = now.strftime("%Y-%m-%d %H:%M KST")
    html = read_asset("report.html").replace("{{REPORT_STYLE}}", read_asset("report.css")).replace(
        "{{REPORT_SCRIPT}}", read_asset("report.js"))
    for old, new in [
        ("PROJECT_NAME", project_label), ("YEAR", str(year)), ("CREATED_TOTAL", created_txt),
        ("RESOLVED_TOTAL", resolved_txt), ("RATIO_VALUE", ratio_txt),
        ("GENERATION_TIME", generated), ("CHART_DATA", data),
        ("PERIOD_DATA", period_json),
        ("REPORTER_NAMES", escape(", ".join(reporters))),
    ]:
        html = html.replace(old, new)
    return html
