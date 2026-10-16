"""Real local server handoff with synthetic credentials and temporary state."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import subprocess
import sys
import threading
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from jira_credentials import Credentials
import jira_dashboard_lifecycle as lifecycle
import jira_paths
from jira_web import DashboardServer

STOP_LEGACY = lifecycle.stop_legacy_launchers


class RestartTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(jira_paths, 'D_LOCAL', Path(directory.name)))
        self.legacy = self.stack.enter_context(patch.object(lifecycle, 'stop_legacy_launchers'))
        self.creds = Credentials('https://jira.internal', 'sample', 'synthetic-private-password')

    def test_new_launch_stops_previous_server_reuses_port_and_preserves_new_state(self):
        ready = threading.Event()
        first = []
        errors = []
        def run():
            try:
                with lifecycle.restarting_dashboard(DashboardServer, self.creds, [], []) as server:
                    first.append(server)
                    ready.set()
                    server.serve_forever(poll_interval=.01)
            except Exception as error:
                errors.append(error)
                ready.set()
        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        self.assertTrue(ready.wait(3))
        self.assertEqual(errors, [])
        try:
            with contextlib.redirect_stdout(io.StringIO()), lifecycle.restarting_dashboard(DashboardServer, self.creds, [], []) as second:
                self.assertEqual(second.server_port, first[0].server_port)
                self.assertNotEqual(second.session, first[0].session)
                thread.join(timeout=3)
                self.assertFalse(thread.is_alive())
                self.assertEqual(errors, [])
                state = lifecycle.read_state()
                self.assertEqual(state['session'], second.session)
                self.assertNotIn(self.creds.token, lifecycle.state_path().read_text())
        finally:
            if thread.is_alive():
                first[0].shutdown()
                thread.join(timeout=3)
        self.assertFalse(lifecycle.state_path().exists())

    def test_bad_or_foreign_state_is_ignored(self):
        for text in ('not-json', '[]', '{}', json.dumps({'application': 'other-app', 'port': 1234})):
            lifecycle.state_path().write_text(text)
            with patch.object(lifecycle, 'build_opener') as opener:
                self.assertIsNone(lifecycle.stop_previous())
                opener.assert_not_called()

    @unittest.skipUnless(os.name == 'nt', 'Legacy process discovery uses Windows CIM')
    def test_legacy_cleanup_stops_only_the_exact_workspace_launcher(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            launcher = root / 'cores' / 'python' / 'launch_report.py'
            launcher.parent.mkdir(parents=True)
            other = root / 'other_app.py'
            for script in (launcher, other):
                script.write_text('import time\ntime.sleep(30)\n')
            processes = [subprocess.Popen([sys.executable, str(script)], stdout=subprocess.DEVNULL,
                                          stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
                         for script in (launcher, other)]
            try:
                with patch.object(jira_paths, 'D_PROJECT', root), contextlib.redirect_stdout(io.StringIO()):
                    STOP_LEGACY()
                processes[0].wait(timeout=3)
                self.assertIsNone(processes[1].poll(), 'An unrelated Python app must remain running')
            finally:
                for process in processes:
                    if process.poll() is None:
                        process.terminate()
                    process.wait(timeout=3)

    def test_shutdown_requires_the_current_session(self):
        server = DashboardServer(self.creds, [], [])
        thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=.01), daemon=True)
        thread.start()
        try:
            request = Request(server.origin + '/api/shutdown', data=b'{}', headers={
                'Origin': server.origin, 'X-Session-Token': 'wrong', 'Content-Type': 'application/json'})
            with self.assertRaises(HTTPError) as error:
                urlopen(request, timeout=3)
            self.assertEqual(error.exception.code, 403)
            error.exception.close()
            self.assertTrue(thread.is_alive())
            with urlopen(server.origin, timeout=3) as response:
                self.assertEqual(response.status, 200)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)
