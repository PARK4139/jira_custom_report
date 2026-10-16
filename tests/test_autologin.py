"""Opt-in auto login: storage rules, the dashboard endpoint and button state, and how the launcher uses a saved login."""
import contextlib
import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import jira_autologin as autologin
import jira_dashboard_cli as cli
import jira_dashboard_server as web
import jira_inputs
from jira_credentials import Credentials
from jira_dashboard_ui import dashboard_html

SECRET = "synthetic-autologin-secret"


class FakeVault:
    def __init__(self):
        self.items = {}
        self.fail = False

    def get_password(self, service, name):
        if self.fail:
            raise OSError(SECRET)
        return self.items.get((service, name))

    def set_password(self, service, name, value):
        if self.fail:
            raise OSError(SECRET)
        self.items[(service, name)] = value

    def delete_password(self, service, name):
        if self.fail:
            raise OSError(SECRET)
        self.items.pop((service, name), None)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.vault = FakeVault()
        patcher = patch.object(autologin, "_vault", return_value=self.vault)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.credentials = Credentials("https://jira.example.com/jira", "sample", SECRET)
        self.store = autologin.WindowsAutoLogin("default")

    def test_nothing_is_saved_until_it_is_enabled_and_disabling_deletes_it(self):
        self.assertFalse(self.store.enabled())
        self.assertEqual(self.vault.items, {})
        self.store.enable(self.credentials)
        self.assertTrue(self.store.enabled())
        self.assertEqual(self.store.load(), self.credentials)
        self.store.disable()
        self.assertFalse(self.store.enabled())
        self.assertEqual(self.vault.items, {})
        self.store.disable()  # disabling twice is harmless

    def test_entry_is_separate_from_the_cli_password_profile_and_holds_no_extra_data(self):
        self.store.enable(self.credentials)
        ((service, name), raw), = self.vault.items.items()
        self.assertEqual((service, name), ("jira-custom-report", "dashboard-default"))
        self.assertEqual(json.loads(raw), {"url": "https://jira.example.com/jira", "email": "sample", "token": SECRET})
        self.assertEqual(autologin.WindowsAutoLogin("team-a").entry, "dashboard-team-a")
        for profile in ("../x", "a b", "", "x" * 64, "con"):
            with self.subTest(profile=profile), self.assertRaises(ValueError):
                autologin.WindowsAutoLogin(profile)

    def test_a_saved_login_is_only_used_for_its_own_server_and_user(self):
        self.store.enable(self.credentials)
        self.assertEqual(self.store.load("https://JIRA.example.com/jira/", "sample"), self.credentials, "case and a trailing slash do not matter")
        self.assertIsNone(self.store.load("https://other.example.com/jira", "sample"), "never send the password to another server")
        self.assertIsNone(self.store.load("https://jira.example.com/other", "sample"))
        self.assertIsNone(self.store.load("http://jira.example.com/jira", "sample"), "a different scheme is a different server")
        self.assertIsNone(self.store.load("https://jira.example.com:8443/jira", "sample"))
        self.assertIsNone(self.store.load("https://jira.example.com/jira", "someone-else"))
        self.assertEqual(self.store.load(None, None), self.credentials)

    def test_plain_http_logins_keep_their_explicit_opt_in(self):
        http = Credentials("http://jira.internal", "sample", SECRET, allow_insecure_http=True)
        self.store.enable(http)
        loaded = self.store.load()
        self.assertTrue(loaded.allow_insecure_http)
        self.assertEqual(loaded.url, "http://jira.internal")

    def test_unreadable_or_damaged_entries_mean_no_saved_login(self):
        self.store.enable(self.credentials)
        key = next(iter(self.vault.items))
        for raw in ("not json", "[]", json.dumps({"url": "https://x"}), json.dumps({"url": "ftp://x", "email": "a", "token": "b"})):
            with self.subTest(raw=raw):
                self.vault.items[key] = raw
                self.assertIsNone(self.store.load())
        self.vault.fail = True
        self.assertFalse(self.store.enabled())
        self.assertIsNone(self.store.load())

    def test_failures_never_leak_the_secret(self):
        self.vault.fail = True
        for action in (lambda: self.store.enable(self.credentials), self.store.disable):
            with self.assertRaises(RuntimeError) as error:
                action()
            self.assertNotIn(SECRET, str(error.exception))

    def test_memory_store_behaves_like_the_real_one_and_no_store_is_unavailable(self):
        memory = autologin.MemoryAutoLogin()
        self.assertTrue(memory.available and not memory.enabled())
        memory.enable(self.credentials)
        self.assertTrue(memory.enabled())
        memory.disable()
        self.assertFalse(memory.enabled())
        none = autologin.NoAutoLogin()
        self.assertFalse(none.available or none.enabled())
        with self.assertRaises(RuntimeError):
            none.enable(self.credentials)


class DashboardEndpointTests(unittest.TestCase):
    def start(self, store):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        patcher = patch.object(jira_inputs, "F_INPUTS", Path(directory.name) / "inputs.json")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.credentials = Credentials("https://jira.internal/jira", "sample-user", SECRET)
        self.server = web.DashboardServer(self.credentials, ["DEMO"], ["sample"], autologin=store)
        thread = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=.01), daemon=True)
        thread.start()
        self.addCleanup(lambda: (self.server.shutdown(), self.server.server_close(), thread.join(timeout=2)))

    def request(self, payload=None, path="/api/autologin", **headers):
        defaults = {"Origin": self.server.origin, "X-Session-Token": self.server.session, "Content-Type": "application/json"}
        defaults.update(headers)
        request = Request(self.server.origin + path, data=None if payload is None else json.dumps(payload).encode(), headers=defaults)
        try:
            with urlopen(request, timeout=5) as response:
                return response.status, response.read().decode()
        except HTTPError as error:
            with error:
                return error.code, error.read().decode()

    def test_turning_it_on_saves_the_current_login_and_turning_it_off_removes_it(self):
        store = autologin.MemoryAutoLogin()
        self.start(store)
        self.assertEqual(self.request({"enabled": True}), (200, json.dumps({"enabled": True})))
        self.assertEqual(store.load(), self.credentials)
        self.assertIn('"enabled": true', self.request(path="/")[1].split('"autoLogin":', 1)[1].split("}", 1)[0])
        self.assertEqual(self.request({"enabled": False}), (200, json.dumps({"enabled": False})))
        self.assertIsNone(store.load())

    def test_the_page_never_contains_the_password_and_reports_the_button_state(self):
        self.start(autologin.MemoryAutoLogin())
        page = self.request(path="/")[1]
        self.assertNotIn(SECRET, page)
        self.assertIn('"autoLogin": {"available": true, "enabled": false}', page)
        self.assertIn('id="autologin"', page)
        self.start(autologin.NoAutoLogin())
        self.assertIn('"autoLogin": {"available": false, "enabled": false}', self.request(path="/")[1])

    def test_requests_need_the_session_and_a_strict_payload(self):
        store = autologin.MemoryAutoLogin()
        self.start(store)
        self.assertEqual(self.request({"enabled": True}, **{"X-Session-Token": "bad"})[0], 403)
        self.assertEqual(self.request({"enabled": True}, Origin="https://evil.example")[0], 403)
        for payload in ({}, {"enabled": "yes"}, {"enabled": 1}, {"enabled": None}, {"enabled": True, "extra": 1}, []):
            with self.subTest(payload=payload):
                self.assertEqual(self.request(payload)[0], 400)
        self.assertFalse(store.enabled())

    def test_unavailable_store_and_storage_errors_are_reported_without_secrets(self):
        self.start(autologin.NoAutoLogin())
        self.assertEqual(self.request({"enabled": True})[0], 404)
        store = autologin.MemoryAutoLogin()
        store.enable = lambda credentials: (_ for _ in ()).throw(RuntimeError("Could not save the login in Windows Credential Manager."))
        self.start(store)
        code, body = self.request({"enabled": True})
        self.assertEqual(code, 500)
        self.assertNotIn(SECRET, body)
        self.assertIn("Windows Credential Manager", body)

    def test_page_html_default_has_no_auto_login(self):
        self.assertIn('"autoLogin": {"available": false, "enabled": false}', dashboard_html("s", "DEMO", ["x"], 2026))


class FakeStore:
    available = True

    def __init__(self, saved=None):
        self.saved = saved
        self.loads = []

    def load(self, url=None, user_id=None):
        self.loads.append((url, user_id))
        if self.saved is None:
            return None
        if (url is not None and url != self.saved.url) or (user_id is not None and user_id != self.saved.email):
            return None
        return self.saved


class LauncherTests(unittest.TestCase):
    def run_main(self, argv, store):
        started = []

        @contextlib.contextmanager
        def fake_restart(factory, credentials, projects, reporters, port=0):
            started.append(credentials)

            class Server:
                origin = "http://127.0.0.1:1"

                def serve_forever(self):
                    raise KeyboardInterrupt
            yield Server()

        prompted = []

        def prompt(url=None, email=None, allow_insecure_http=False):
            prompted.append((url, email))
            return Credentials("https://typed.example.com", "typed", "typed-password")
        output, errors = io.StringIO(), io.StringIO()
        with patch("sys.argv", ["jira-report", "--no-open", *argv]), patch.object(cli, "WindowsAutoLogin", return_value=store), \
                patch.object(cli, "load_settings", return_value=None), patch.object(cli, "restarting_dashboard", fake_restart), \
                patch.object(cli, "prompt_credentials", prompt), contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            cli.main()
        return started[0], prompted, output.getvalue() + errors.getvalue()

    def test_a_saved_login_starts_the_dashboard_without_any_prompt(self):
        saved = Credentials("https://jira.example.com", "sample", SECRET)
        credentials, prompted, text = self.run_main([], FakeStore(saved))
        self.assertEqual(credentials, saved)
        self.assertEqual(prompted, [])
        self.assertIn("Auto login: using the saved login for sample at https://jira.example.com", text)
        self.assertNotIn(SECRET, text)

    def test_without_a_saved_login_the_password_is_asked_for(self):
        credentials, prompted, text = self.run_main([], FakeStore(None))
        self.assertEqual(len(prompted), 1)
        self.assertEqual(credentials.email, "typed")
        self.assertNotIn("Auto login: using", text)

    def test_a_saved_login_is_never_used_for_another_server_or_user_given_on_the_command_line(self):
        saved = Credentials("https://jira.example.com", "sample", SECRET)
        for argv in (["--url", "https://other.example.com"], ["--id", "someone-else"]):
            with self.subTest(argv=argv):
                credentials, prompted, _ = self.run_main(argv, FakeStore(saved))
                self.assertEqual(len(prompted), 1)
                self.assertEqual(credentials.email, "typed")

    def test_no_auto_login_forces_the_prompt_and_leaves_the_saved_login_alone(self):
        store = FakeStore(Credentials("https://jira.example.com", "sample", SECRET))
        credentials, prompted, _ = self.run_main(["--no-auto-login"], store)
        self.assertEqual(len(prompted), 1)
        self.assertEqual(store.loads, [], "the saved login is not even read")

    def test_plain_http_saved_logins_still_show_the_warning(self):
        saved = Credentials("http://jira.internal", "sample", SECRET, allow_insecure_http=True)
        _, prompted, text = self.run_main([], FakeStore(saved))
        self.assertEqual(prompted, [])
        self.assertTrue("HTTP" in text or "http" in text.lower())
        self.assertNotIn(SECRET, text)


if __name__ == "__main__":
    unittest.main()


class ButtonTests(unittest.TestCase):
    def test_button_behavior_in_the_page_script(self):
        import shutil
        import subprocess
        if not shutil.which("node"):
            self.skipTest("Node is needed to execute frontend behavior checks")
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            pages = []
            for name, state in (("off", {"available": True, "enabled": False}), ("on", {"available": True, "enabled": True}),
                                ("none", {"available": False, "enabled": False})):
                page = Path(directory) / f"{name}.html"
                page.write_text(dashboard_html("synthetic-session", "DEMO", ["sample"], 2026, None, state), encoding="utf-8")
                pages.append(str(page))
            result = subprocess.run(["node", str(root / "tests/check_autologin_button.cjs"), *pages],
                                    capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(__import__("shutil").which("node") and Path("C:/Program Files/Google/Chrome/Application/chrome.exe").exists(), "Node and Chrome are needed")
    def test_real_chrome_button_placement_confirmation_and_state(self):
        import subprocess
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(["node", str(root / "tests/check_autologin_chrome.cjs")], cwd=root,
                                capture_output=True, text=True, encoding="utf-8", timeout=180)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
