"""Parse launcher options, prompt for credentials, and run the dashboard."""
import argparse
import os
import webbrowser

from jira_credentials import prompt_credentials
from jira_dashboard_server import DashboardServer
from jira_dashboard_lifecycle import restarting_dashboard
from jira_settings import load_settings


def open_browser(url):
    try:
        if webbrowser.open_new_tab(url):
            return True
    except (OSError, webbrowser.Error):
        pass
    startfile = getattr(os, 'startfile', None)  # Windows default-handler fallback
    if startfile is None:
        return False
    try:
        startfile(url)
        return True
    except OSError:
        return False


def main():
    parser = argparse.ArgumentParser(description='On-premises Jira web dashboard')
    parser.add_argument('--url', '--site-url', dest='url', help='Jira server base URL (http:// or https://)')
    parser.add_argument('--allow-insecure-http', action='store_true',
                        help=argparse.SUPPRESS)
    parser.add_argument('--id', '--email', dest='user_id', help='Jira user ID')
    parser.add_argument('--project', nargs='+', help='Initial project keys; editable in the browser')
    parser.add_argument('--reporter', nargs='+', help='Initial reporter IDs; editable in the browser')
    parser.add_argument('--profile', default='default', help='Read existing nonsecret defaults')
    parser.add_argument('--port', type=int, default=0, help='Local port (default: automatically allocated)')
    parser.add_argument('--no-open', action='store_true', help='Print the dashboard URL without opening a browser')
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error('port must be between 0 and 65535')
    saved = load_settings(args.profile, allow_insecure_http=True)
    credentials = prompt_credentials(args.url or (saved.site_url if saved else None),
                                     args.user_id or (saved.email if saved else None),
                                     allow_insecure_http=args.allow_insecure_http)
    with restarting_dashboard(DashboardServer, credentials, args.project or (saved.projects if saved else []),
                         args.reporter or (saved.reporters if saved else []), args.port) as server:
        print(f'Dashboard: {server.origin}/')
        print('Select the year in your browser. Keep this terminal open; press Ctrl+C to stop.')
        if not args.no_open and not open_browser(server.origin + '/'):
            print('Open the dashboard URL above in your browser.')
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print('Dashboard stopped.')
