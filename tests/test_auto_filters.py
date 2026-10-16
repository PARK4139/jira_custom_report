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
