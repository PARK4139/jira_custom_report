"""Exercise resource loading after extraction, including installed zip packages."""
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
import zipfile

from jira_dashboard_ui import dashboard_html
from jira_report_view import render_html

ROOT = Path(__file__).resolve().parents[1]


class FrontendAssetsTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node is needed for export checks')
    def test_jpg_export_workflow_and_failure_recovery(self):
        result = subprocess.run(['node', str(ROOT / 'tests/check_jpg_export.cjs'),
                                 str(ROOT / 'cores/html/exports.js')],
                                capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_packaged_assets_render_outside_the_checkout(self):
        config = tomllib.loads((ROOT / 'pyproject.toml').read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / 'installed.zip'
            with zipfile.ZipFile(archive, 'w') as bundle:
                for module in config['tool']['setuptools']['py-modules']:
                    bundle.write(ROOT / f'cores/python/{module}.py', f'{module}.py')
                bundle.write(ROOT / 'cores/__init__.py', 'cores/__init__.py')
                bundle.write(ROOT / 'cores/html/__init__.py', 'cores/html/__init__.py')
                for pattern in config['tool']['setuptools']['package-data']['cores.html']:
                    for asset in (ROOT / 'cores/html').glob(pattern):
                        bundle.write(asset, 'cores/html/' + asset.name)
            code = '''import sys
sys.path.insert(0, sys.argv[1])
from jira_dashboard_ui import dashboard_html
from jira_report_view import render_html
import cores.html
assert 'installed.zip' in cores.html.__file__
page = dashboard_html('synthetic-session', 'DEMO', ['sample'], 2026)
assert 'async function loadReport' in page and 'async function exportJpg' in page
assert '--page:' in page and 'id="period-select"' in page
assert '{{REPORT_' not in page and 'WEB_CONFIG' not in page
assert 'Issue Trend' in render_html('DEMO', 2026, [], [])
'''
            result = subprocess.run([sys.executable, '-I', '-c', code, str(archive)],
                                    cwd=directory, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_dashboard_config_stays_safe_in_an_inline_script(self):
        hostile = '</script><script>alert(1)</script>'
        page = dashboard_html('synthetic-session', hostile, [hostile], 2026)
        self.assertNotIn(hostile, page)
        self.assertEqual(page.count('<script>'), 1)
        config = json.loads(re.search(r'const config=(.*?);\n', page).group(1))
        self.assertEqual(config['project'], hostile)

    @unittest.skipUnless(shutil.which('node'), 'Node is needed for generated-script checks')
    def test_assembled_scripts_and_dashboard_flow(self):
        page = dashboard_html('synthetic-session', 'DEMO', ['sample'], 2026)
        script = re.search(r'<script>([\s\S]*?)</script>', page).group(1)
        result = subprocess.run(['node', '--check', '-'], input=script,
                                capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)
        with tempfile.TemporaryDirectory() as directory:
            dashboard = Path(directory) / 'dashboard.html'
            dashboard.write_text(page, encoding='utf-8')
            result = subprocess.run(['node', str(ROOT / 'tests/check_web_dashboard.cjs'), str(dashboard)],
                                    capture_output=True, text=True, encoding='utf-8')
            self.assertEqual(result.returncode, 0, result.stderr)
            report = Path(directory) / 'report.html'
            from jira_periods import BASE_PERIODS, period_ranges
            periods = {period: [dict(row, created=2, resolved=1) for row in period_ranges(2026, period)]
                       for period in BASE_PERIODS}
            report.write_text(render_html('DEMO', 2026, [], ['sample'], periods), encoding='utf-8')
            result = subprocess.run(['node', str(ROOT / 'tests/check_report_tabs.cjs'), str(report)],
                                    capture_output=True, text=True, encoding='utf-8')
            self.assertEqual(result.returncode, 0, result.stderr)
