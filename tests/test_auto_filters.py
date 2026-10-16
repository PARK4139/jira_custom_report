"""Verify automatic browser requests against the generated dashboard scripts."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from jira_web import dashboard_html


class AutoFilterTests(unittest.TestCase):
    def test_dropdown_controls_replace_the_query_button(self):
        page = dashboard_html('synthetic-session', 'DEMO', ['sample'], 2026)
        self.assertIn('id="period-select"', page)
        self.assertNotIn('id="query-button"', page)

    @unittest.skipUnless(shutil.which('node'), 'Node is needed to execute frontend behavior checks')
    def test_auto_query_period_switching_and_latest_selection_win(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            page = Path(directory) / 'dashboard.html'
            page.write_text(dashboard_html('synthetic-session', 'DEMO', ['sample'], 2026), encoding='utf-8')
            result = subprocess.run(['node', str(root / 'tests/check_auto_filters.cjs'), str(page)],
                                    capture_output=True, text=True, encoding='utf-8', timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)


class SavedInputsTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node is needed to execute frontend behavior checks')
    def test_saved_inputs_restore_seed_local_storage_and_are_mirrored(self):
        root = Path(__file__).resolve().parents[1]
        saved = {'year': '2024', 'period': 'yearly', 'mode': 'periodic', 'locale': 'en', 'theme': 'dark', 'projects': '["OTHER"]',
                 'reporters': '[{"value": "parkjh", "label": "박정훈 (parkjh)"}]'}
        with tempfile.TemporaryDirectory() as directory:
            with_saved, without = Path(directory) / 'saved.html', Path(directory) / 'plain.html'
            with_saved.write_text(dashboard_html('synthetic-session', 'DEMO', ['sample'], 2026, saved), encoding='utf-8')
            without.write_text(dashboard_html('synthetic-session', 'DEMO', ['sample'], 2026), encoding='utf-8')
            result = subprocess.run(['node', str(root / 'tests/check_saved_inputs.cjs'), str(with_saved), str(without)],
                                    capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
