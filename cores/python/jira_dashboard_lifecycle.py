"""Restart only this checkout's dashboard, without terminating other Python apps."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

import jira_paths


def state_path():
    return jira_paths.D_LOCAL / 'dashboard.json'


@contextmanager
def startup_lock():
    jira_paths.D_LOCAL.mkdir(parents=True, exist_ok=True)
    with (jira_paths.D_LOCAL / 'dashboard.lock').open('a+b') as handle:
        if os.fstat(handle.fileno()).st_size == 0:
            handle.write(b'0')
            handle.flush()
        deadline = time.monotonic() + 10
        while True:
            try:
                handle.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise RuntimeError('Another dashboard launch is in progress. Try again shortly.') from None
                time.sleep(.05)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def read_state():
    try:
        value = json.loads(state_path().read_text(encoding='utf-8'))
        if (value.get('application') != 'jira-custom-report'
                or value.get('workspace') != str(jira_paths.D_PROJECT.resolve())
                or type(value.get('port')) is not int or not 1 <= value['port'] <= 65535
                or not isinstance(value.get('session'), str)
                or not re.fullmatch(r'[A-Za-z0-9_-]{32,128}', value['session'])):
            return None
        return value
    except (OSError, ValueError, AttributeError):
        return None


def stop_previous():
    state = read_state()
    if state is None:
        return None
    origin = f"http://127.0.0.1:{state['port']}"
    request = Request(origin + '/api/shutdown', data=b'{}',
                      headers={'Origin': origin, 'X-Session-Token': state['session'],
                               'Content-Type': 'application/json'}, method='POST')
    try:
        with build_opener(ProxyHandler({})).open(request, timeout=3) as response:
            result = json.load(response)
        if result != {'application': 'jira-custom-report', 'stopping': True}:
            return None
    except (HTTPError, URLError, OSError, ValueError):
        return None
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        with socket.socket() as connection:
            connection.settimeout(.2)
            if connection.connect_ex(('127.0.0.1', state['port'])) != 0:
                print('Previous dashboard stopped.')
                return state['port']
        time.sleep(.05)
    raise RuntimeError('Previous dashboard did not stop in time. Close its terminal and retry.')


def stop_legacy_launchers():
    if os.name != 'nt':
        return
    # Older versions have no state file. Match the exact absolute launcher
    # argument used by run.cmd; never kill by Python executable name or port.
    script = r'''
$pattern = '^(?:"[^"]+"|\S+)\s+"?' + [regex]::Escape($env:JIRA_DASHBOARD_LAUNCHER) + '"?(?:\s|$)'
$stopped = 0
Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" -ErrorAction Stop |
    Where-Object { $_.ProcessId -ne [int]$env:JIRA_DASHBOARD_CURRENT_PID -and $_.ProcessId -ne [int]$env:JIRA_DASHBOARD_PARENT_PID -and $_.CommandLine -match $pattern } |
    ForEach-Object {
        try { Stop-Process -Id $_.ProcessId -ErrorAction Stop; $stopped++ }
        catch { if (Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue) { throw } }
    }
Write-Output $stopped
'''
    environment = dict(os.environ, JIRA_DASHBOARD_LAUNCHER=str(jira_paths.D_PROJECT / 'cores' / 'python' / 'launch_report.py'),
                       JIRA_DASHBOARD_CURRENT_PID=str(os.getpid()),
                       # venv python.exe is a launcher stub that parents the real interpreter.
                       JIRA_DASHBOARD_PARENT_PID=str(os.getppid()))
    try:
        result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                                capture_output=True, text=True, env=environment, timeout=15,
                                creationflags=subprocess.CREATE_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeError('Could not inspect older dashboard launchers. Close their terminals and retry.') from None
    if result.returncode:
        raise RuntimeError('Could not stop an older dashboard launcher. Close its terminal and retry.')
    if result.stdout.strip() != '0':
        print('Previous dashboard launcher stopped.')


@contextmanager
def restarting_dashboard(factory, credentials, projects, reporters, port=0):
    with startup_lock():
        previous_port = stop_previous()
        stop_legacy_launchers()
        server = factory(credentials, projects, reporters, port or previous_port or 0)
        state = {'application': 'jira-custom-report', 'workspace': str(jira_paths.D_PROJECT.resolve()),
                 'pid': os.getpid(), 'port': server.server_port, 'session': server.session}
        pending = state_path().with_suffix(f'.{os.getpid()}.pending')
        try:
            pending.write_text(json.dumps(state), encoding='utf-8')
            pending.replace(state_path())
        except OSError:
            server.server_close()
            raise
        finally:
            pending.unlink(missing_ok=True)
    try:
        with server:
            yield server
    finally:
        with startup_lock():
            current = read_state()
            if current and current['session'] == server.session:
                state_path().unlink(missing_ok=True)
