"""Calendar-year buckets shared by JQL, report tables, and exports."""
from datetime import date, timedelta
import json

PERIODS = ("1week", "2week", "monthly", "yearly")


def period_ranges(year: int, period: str) -> list[dict]:
    if period not in PERIODS or type(year) is not int or not 2 <= year <= 9998:
        raise ValueError("Choose a supported period and a year between 2 and 9998.")
    start, end = date(year, 1, 1), date(year + 1, 1, 1)
    ranges = []
    while start < end:
        if period == "monthly":
            stop = date(year + 1, 1, 1) if start.month == 12 else date(year, start.month + 1, 1)
            label = f"{start.month:02d}"
        elif period == "yearly":
            stop, label = end, str(year)
        else:
            stop = min(start + timedelta(days=7 if period == "1week" else 14), end)
            label = f"{start:%m/%d}"
        ranges.append({"label": label, "start": str(start), "end": str(stop)})
        start = stop
    return ranges


def period_jql(project: str, reporters: list[str], start: str, end: str, date_field: str) -> str:
    if date_field not in ("created", "resolved"):
        raise ValueError("JQL supports only created or resolved.")
    if date.fromisoformat(start) >= date.fromisoformat(end):
        raise ValueError("JQL end must be after start.")
    names = ", ".join(json.dumps(name, ensure_ascii=False) for name in reporters)
    return (f"project = {json.dumps(project, ensure_ascii=False)} AND reporter IN ({names}) "
            f'AND {date_field} >= "{start}" AND {date_field} < "{end}"')
