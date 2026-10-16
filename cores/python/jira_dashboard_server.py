"""Loopback HTTP boundary: session checks, validation, and safe responses."""
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import re
import secrets
import subprocess
import sys
import threading

from jira_credentials import Credentials
from jira_dashboard_service import build_report
from jira_dashboard_ui import dashboard_html
from jira_inputs import load_inputs, save_inputs
from jira_issue_monthly import TZ
from jira_paths import D_OUTPUTS
from jira_projects import fetch_projects
from jira_reporters import search_reporters
from jira_settings import Settings


def reveal_output(path):
    """Show a saved file in the OS file manager; failures are not worth interrupting the export."""
    try:
        if os.name == 'nt':
            subprocess.Popen(f'explorer /select,"{path}"')
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', '-R', str(path)])
        else:
            subprocess.Popen(['xdg-open', str(path.parent)])
    except OSError:
        pass


class DashboardServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, credentials: Credentials, projects: list[str], reporters: list[str], port: int = 0):
        super().__init__(("127.0.0.1", port), DashboardHandler)
        self.credentials = credentials
        self.projects, self.reporters = projects, reporters
        self.project_names = {}
        self.session = secrets.token_urlsafe(32)
        self.query_lock = threading.Lock()
        self.current_year = datetime.now(TZ).year
        self.origin = f"http://127.0.0.1:{self.server_port}"


class DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # Do not log filters or credentials.

    def respond(self, code: int, payload, content_type="application/json"):
        body = payload.encode('utf-8') if isinstance(payload, str) else json.dumps(payload).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', content_type + '; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src blob:; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def trusted_host(self):
        return self.headers.get('Host') == self.server.origin.removeprefix('http://')

    def do_GET(self):
        if not self.trusted_host():
            self.respond(403, {'error': 'Untrusted host.'})
        elif self.path == '/':
            self.respond(200, dashboard_html(self.server.session, ' '.join(self.server.projects),
                                            self.server.reporters, self.server.current_year, load_inputs()), 'text/html')
        else:
            self.respond(404, {'error': 'Not found.'})

    def discard_body(self):
        # Drain small rejected requests so Windows does not reset the connection
        # before the browser can read the error response.
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if 0 < length <= 65536:
                self.connection.settimeout(2)
                self.rfile.read(length)
        except (ValueError, OSError):
            pass

    def do_POST(self):
        if (not self.trusted_host() or self.headers.get('Origin') != self.server.origin
                or not secrets.compare_digest(self.headers.get('X-Session-Token', ''), self.server.session)):
            self.discard_body()
            self.respond(403, {'error': 'Untrusted request. Open the dashboard from the launcher URL.'})
            return
        if self.path == '/api/output':
            self.save_output()
            return
        if self.path not in ('/api/report', '/api/projects', '/api/reporters', '/api/inputs', '/api/shutdown'):
            self.discard_body()
            self.respond(404, {'error': 'Not found.'})
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 65536 or self.headers.get('Content-Type') != 'application/json':
                raise ValueError
            payload = json.loads(self.rfile.read(length))
            if self.path == '/api/shutdown':
                if payload != {}:
                    raise ValueError
                self.respond(200, {'application': 'jira-custom-report', 'stopping': True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            if self.path == '/api/projects':
                if payload != {}:
                    raise ValueError
                try:
                    projects = fetch_projects(self.server.credentials)
                except RuntimeError as error:
                    self.respond(502, {'error': str(error)})
                except Exception:
                    self.respond(500, {'error': 'Could not load Jira projects. Try reloading the list.'})
                else:
                    self.server.project_names = {project['key']: project['name'] for project in projects}
                    self.respond(200, {'projects': projects})
                return
            if self.path == '/api/inputs':
                if not isinstance(payload, dict) or set(payload) != {'values'}:
                    raise ValueError
                try:
                    save_inputs(payload['values'])
                except ValueError:
                    self.respond(400, {'error': 'Invalid dashboard inputs.'})
                except OSError:
                    self.respond(500, {'error': 'Could not save the dashboard inputs.'})
                else:
                    self.respond(200, {'saved': True})
                return
            if self.path == '/api/reporters':
                if not isinstance(payload, dict) or set(payload) != {'query'}:
                    raise ValueError
                try:
                    reporters = search_reporters(self.server.credentials, payload['query'])
                except ValueError:
                    self.respond(400, {'error': 'Enter a shorter reporter search without control characters.'})
                except RuntimeError as error:
                    self.respond(502, {'error': str(error)})
                except Exception:
                    self.respond(500, {'error': 'Could not search Jira users. Try again.'})
                else:
                    self.respond(200, {'reporters': reporters})
                return
            if not isinstance(payload, dict) or set(payload) != {'year', 'projects', 'reporters'}:
                raise ValueError
            year = payload['year']
            if type(year) is not int or not 1970 <= year <= self.server.current_year + 1:
                raise ValueError
            settings = Settings(self.server.credentials.url, self.server.credentials.email,
                                payload['projects'], payload['reporters'], year,
                                allow_insecure_http=self.server.credentials.allow_insecure_http)
            if len(settings.projects) > 20 or len(settings.reporters) > 100:
                raise ValueError
        except (ValueError, TypeError, KeyError, UnicodeError):
            self.respond(400, {'error': 'Select a valid year, projects, and reporters.'})
            return
        if not self.server.query_lock.acquire(blocking=False):
            self.respond(409, {'error': 'Another query is running. Try again when it finishes.'})
            return
        try:
            status, response = 200, build_report(settings, self.server.credentials, self.server.project_names)
        except RuntimeError as error:
            status, response = 502, {'error': str(error)}
        except Exception:
            status, response = 500, {'error': 'Could not complete the Jira query. Check the terminal and retry.'}
        finally:
            self.server.query_lock.release()
        self.respond(status, response)

    def save_output(self):
        name = self.headers.get('X-Output-Name', '')
        content_type = self.headers.get('Content-Type', '')
        is_jpg = bool(re.fullmatch(r'jira_\d{8}-\d{6}_\d{4}_(?:1week|2week|monthly|yearly)_(?:ko|en)_(?:light|dark)\.jpg', name))
        is_csv = bool(re.fullmatch(r'jira_\d{8}-\d{6}_\d{4}_issues\.csv', name))
        if not ((is_jpg and content_type == 'image/jpeg') or
                (is_csv and content_type == 'text/csv;charset=utf-8')):
            self.discard_body()
            self.respond(400, {'error': 'Invalid report export.'})
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            length = 0
        if not 4 <= length <= 20 * 1024 * 1024:
            self.discard_body()
            self.respond(413, {'error': 'Report export must be under 20 MB.'})
            return
        data = self.rfile.read(length)
        valid_data = len(data) == length
        if is_jpg:
            valid_data = valid_data and data.startswith(b'\xff\xd8\xff') and data.endswith(b'\xff\xd9')
        else:
            try:
                data.decode('utf-8-sig')
            except UnicodeDecodeError:
                valid_data = False
        if not valid_data:
            self.respond(400, {'error': 'Invalid report data.'})
            return
        try:
            D_OUTPUTS.mkdir(parents=True, exist_ok=True)
        except OSError:
            self.respond(500, {'error': 'Could not create the outputs directory.'})
            return
        stem, extension = name.rsplit('.', 1)
        for suffix in range(1000):
            filename = name if suffix == 0 else f'{stem}_{suffix:03}.{extension}'
            target = D_OUTPUTS / filename
            opened = False
            try:
                with target.open('xb') as output:
                    opened = True
                    output.write(data)
            except FileExistsError:
                continue
            except OSError:
                if opened:
                    target.unlink(missing_ok=True)
                self.respond(500, {'error': 'Could not save the report in outputs.'})
                return
            if extension == 'jpg':
                reveal_output(target.resolve())
            self.respond(201, {'saved': f'outputs/{filename}'})
            return
        self.respond(409, {'error': 'Could not allocate a unique JPG filename.'})
