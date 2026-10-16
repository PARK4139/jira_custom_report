"""Calendar-year buckets shared by JQL, report tables, and exports."""
from datetime import date, timedelta
import json

BASE_PERIODS = ("1week", "monthly", "yearly")
PERIODS = BASE_PERIODS + ("quarterly", "daily")


def period_ranges(year: int, period: str) -> list[dict]:
    if period not in PERIODS or type(year) is not int or not 2 <= year <= 9998:
        raise ValueError("Choose a supported period and a year between 2 and 9998.")
    start, end = date(year, 1, 1), date(year + 1, 1, 1)
    ranges = []
    while start < end:
        if period == "monthly":
            stop = date(year + 1, 1, 1) if start.month == 12 else date(year, start.month + 1, 1)
            label = f"{start.month:02d}"
        elif period == "daily":
            stop = start + timedelta(days=1)
            label = f"{start:%m/%d}"
        elif period == "quarterly":
            stop = date(year + 1, 1, 1) if start.month == 10 else date(year, start.month + 3, 1)
            label = f"Q{(start.month - 1) // 3 + 1}"
        elif period == "yearly":
            stop, label = end, str(year)
        else:
            stop = min(start + timedelta(days=7), end)
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


def unresolved_jql(project: str, reporters: list[str], start: str, end: str) -> str:
    """Issues whose resolution field was empty on the final calendar day of a bucket."""
    from datetime import date, timedelta
    if date.fromisoformat(start) >= date.fromisoformat(end):
        raise ValueError("JQL end must be after start.")
    names = ", ".join(json.dumps(name, ensure_ascii=False) for name in reporters)
    as_of = date.fromisoformat(end) - timedelta(days=1)
    return (f"project = {json.dumps(project, ensure_ascii=False)} AND reporter IN ({names}) "
            f'AND created < "{end}" AND resolution WAS EMPTY ON "{as_of}"')
