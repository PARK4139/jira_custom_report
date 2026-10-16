"""A saved JPG is revealed in the file manager; CSV exports are not."""
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen

from jira_credentials import Credentials
import jira_dashboard_server as web


class OutputRevealTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.outputs = Path(temporary.name)
        self.server = web.DashboardServer(Credentials('https://jira.internal', 'sample', 'synthetic-secret'), ['DEMO'], ['sample'])
        thread = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=.01), daemon=True)
        thread.start()
        self.addCleanup(lambda: (self.server.shutdown(), self.server.server_close(), thread.join(timeout=2)))

    def save(self, name, content_type, body):
        request = Request(self.server.origin + '/api/output', data=body, headers={
            'Origin': self.server.origin, 'X-Session-Token': self.server.session,
            'Content-Type': content_type, 'X-Output-Name': name})
        with urlopen(request, timeout=5) as response:
            return response.status

    def test_jpg_save_reveals_the_saved_file(self):
        with patch.object(web, 'D_OUTPUTS', self.outputs), patch.object(web, 'reveal_output') as reveal:
            self.assertEqual(self.save('jira_20260101-000000_2026_monthly_ko_light.jpg', 'image/jpeg', b'\xff\xd8\xff\xe0jpeg\xff\xd9'), 201)
        reveal.assert_called_once_with((self.outputs / 'jira_20260101-000000_2026_monthly_ko_light.jpg').resolve())

    def test_csv_save_does_not_open_the_file_manager(self):
        with patch.object(web, 'D_OUTPUTS', self.outputs), patch.object(web, 'reveal_output') as reveal:
            self.assertEqual(self.save('jira_20260101-000000_2026_issues.csv', 'text/csv;charset=utf-8', b'a,b\r\n1,2'), 201)
        reveal.assert_not_called()


if __name__ == '__main__':
    unittest.main()
