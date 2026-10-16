"""Public dashboard entry point; implementation lives in focused modules."""
from jira_dashboard_cli import main
from jira_dashboard_server import DashboardHandler, DashboardServer
from jira_dashboard_ui import dashboard_html
from jira_projects import fetch_projects

__all__ = ["main", "DashboardHandler", "DashboardServer", "dashboard_html", "fetch_projects"]


if __name__ == "__main__":
    main()
