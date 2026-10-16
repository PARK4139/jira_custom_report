"""The QUICK START guide must stay consistent with the repository: its images exist and its commands are real."""
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))  # build_showreel.py lives next to the tests
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


def gif_info(path: Path) -> dict:
    """Read the size, loop flag, and frame delays of a GIF without any image library."""
    data = path.read_bytes()
    assert data[:6] in (b"GIF87a", b"GIF89a")
    width, height = int.from_bytes(data[6:8], "little"), int.from_bytes(data[8:10], "little")
    position = 13
    if data[10] & 0x80:
        position += 3 * (2 << (data[10] & 7))
    delays, loops = [], b"NETSCAPE2.0" in data[:position + 64]
    while position < len(data):
        block = data[position]
        if block == 0x21:  # extension
            label = data[position + 1]
            if label == 0xF9:
                delays.append(int.from_bytes(data[position + 4:position + 6], "little") * 10)
            position += 2
            while data[position]:
                position += data[position] + 1
            position += 1
        elif block == 0x2C:  # image
            flags = data[position + 9]
            position += 10 + (3 * (2 << (flags & 7)) if flags & 0x80 else 0) + 1
            while data[position]:
                position += data[position] + 1
            position += 1
        else:
            break
    return {"width": width, "height": height, "loops": loops, "delays": delays}


class ShowreelTests(unittest.TestCase):
    def test_the_gif_is_exactly_ten_seconds_loops_and_stays_small(self):
        path = ROOT / "docs" / "showreel.gif"
        info = gif_info(path)
        self.assertEqual((info["width"], info["height"]), (960, 540))
        self.assertEqual(sum(info["delays"]), 10_000, "the showreel lasts exactly 10 seconds")
        self.assertGreaterEqual(len(info["delays"]), 20, "a real animation, not a slideshow")
        self.assertTrue(info["loops"], "it loops")
        self.assertLess(path.stat().st_size, 3_000_000, "small enough to embed in the README")
        self.assertTrue(all(delay >= 20 for delay in info["delays"]), "no frame is shorter than browsers can show")

    def test_readme_embeds_it_once_with_an_honest_caption(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertEqual(readme.count("<!-- showreel:start -->"), 1)
        self.assertEqual(readme.count("<!-- showreel:end -->"), 1)
        block = readme.split("<!-- showreel:start -->", 1)[1].split("<!-- showreel:end -->", 1)[0]
        self.assertIn("](docs/showreel.gif)", block)
        self.assertIn("dummy data", block)
        self.assertIn("real console messages", block)

    def test_upsert_inserts_updates_and_is_idempotent(self):
        import tempfile
        import build_showreel as reel
        original = reel.README
        try:
            with tempfile.TemporaryDirectory() as directory:
                reel.README = Path(directory) / "README.md"
                reel.README.write_text("# T\n\n> see [QUICK START GUIDE](QUICK_START.md)\n\nbody\n", encoding="utf-8")
                self.assertEqual(reel.upsert_readme(), "inserted")
                once = reel.README.read_text(encoding="utf-8")
                self.assertEqual(once.count(reel.START), 1)
                self.assertTrue(once.index("QUICK_START.md") < once.index(reel.START) < once.index("body"))
                self.assertEqual(reel.upsert_readme(), "unchanged")
                reel.README.write_text(once.replace("10-second showreel", "OLD TEXT"), encoding="utf-8")
                self.assertEqual(reel.upsert_readme(), "updated")
                self.assertEqual(reel.README.read_text(encoding="utf-8"), once, "an edited block is replaced, not duplicated")
                reel.README.write_text("# no link here\n", encoding="utf-8")
                with self.assertRaises(SystemExit):
                    reel.upsert_readme()
        finally:
            reel.README = original
