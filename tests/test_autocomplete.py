"""Run the autocomplete component checks in Node against the packaged combo.js asset."""
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class AutocompleteTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node is needed to execute frontend behavior checks')
    def test_fuzzy_candidates_and_tab_completion(self):
        result = subprocess.run(['node', str(ROOT / 'tests/check_combo.cjs'), str(ROOT / 'cores/html/combo.js')],
                                capture_output=True, text=True, encoding='utf-8', timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(shutil.which('node') and Path('C:/Program Files/Google/Chrome/Application/chrome.exe').exists(), 'Node and Chrome are needed')
    def test_real_chrome_keyboard_flow_against_synthetic_fixture(self):
        result = subprocess.run(['node', str(ROOT / 'tests/check_autocomplete_chrome.cjs')], cwd=ROOT,
                                capture_output=True, text=True, encoding='utf-8', timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_dashboard_page_ships_the_component_and_text_inputs(self):
        from jira_web import dashboard_html
        page = dashboard_html('synthetic-session', 'DEMO', ['sample'], 2026)
        self.assertIn('function attachCombo', page)
        self.assertIn('<input id="projects"', page)
        self.assertIn('<input id="reporters"', page)
        self.assertNotIn('reload-projects', page)


if __name__ == '__main__':
    unittest.main()
