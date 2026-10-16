"""The QUICK START guide must stay consistent with the repository: its images exist and its commands are real."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
GUIDE = (ROOT / "QUICK_START.md").read_text(encoding="utf-8")


class QuickStartTests(unittest.TestCase):
    def test_every_image_exists_and_is_a_png(self):
        images = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", GUIDE)
        self.assertGreaterEqual(len(images), 9)
        for image in images:
            path = ROOT / image
            with self.subTest(image=image):
                self.assertTrue(path.is_file(), image)
                self.assertEqual(path.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
                self.assertLess(path.stat().st_size, 400_000, "screenshots stay small enough for the repository")

    def test_internal_links_point_to_real_headings(self):
        headings = {re.sub(r"[^\w\- ]", "", h.strip().lower()).replace(" ", "-") for h in re.findall(r"^#{1,4} (.+)$", GUIDE, re.M)}
        for anchor in re.findall(r"\]\(#([^)]+)\)", GUIDE):
            with self.subTest(anchor=anchor):
                self.assertIn(anchor, headings)

    def test_documented_commands_and_options_exist(self):
        self.assertTrue((ROOT / "run.cmd").is_file() and (ROOT / "demo.cmd").is_file())
        import jira_dashboard_cli
        import inspect
        source = inspect.getsource(jira_dashboard_cli.main)
        for option in re.findall(r"^\| `(--[a-z-]+)", GUIDE, re.M):
            with self.subTest(option=option):
                self.assertIn(f"'{option}'", source)
        self.assertIn("git clone https://github.com/PARK4139/Jira_custom_report", GUIDE)
        self.assertIn("run.cmd --url {Jira-server-url} --id {Jira-user-id}", GUIDE)

    def test_the_guide_shows_only_dummy_data_and_no_secrets(self):
        for forbidden in ("password=", "token", "@huvitz", "HTG", "HRKT"):
            with self.subTest(word=forbidden):
                self.assertNotIn(forbidden, GUIDE)


if __name__ == "__main__":
    unittest.main()
