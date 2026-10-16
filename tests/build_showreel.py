"""Builds docs/showreel.gif (exactly 10 s) from the frames written by tests/capture_showreel.cjs.

    node tests/capture_showreel.cjs
    uv run --no-project --with pillow python tests/build_showreel.py

Pillow is only needed to build the GIF, so it is not a project dependency.
"""
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRAMES = ROOT / ".local" / "showreel" / "frames"
TIMELINE = ROOT / ".local" / "showreel" / "timeline.json"
OUTPUT = ROOT / "docs" / "showreel.gif"
TOTAL_MS = 10_000
WIDTH, HEIGHT = 960, 540
COLORS = 128


def scaled_durations(items: list[dict]) -> list[int]:
    """Stretch or shrink only the 'hold' frames so the reel lasts exactly TOTAL_MS (GIF delays are multiples of 10 ms)."""
    fixed = sum(item["ms"] for item in items if not item["hold"])
    holds = sum(item["ms"] for item in items if item["hold"])
    if holds and fixed < TOTAL_MS:
        factor = (TOTAL_MS - fixed) / holds
    else:
        factor = TOTAL_MS / sum(item["ms"] for item in items)
        fixed = 0
    durations = [max(20, round((item["ms"] * (factor if item["hold"] or not fixed else 1)) / 10) * 10) for item in items]
    durations[-1] += TOTAL_MS - sum(durations)  # absorb rounding in the end card
    return durations


README = ROOT / "README.md"
START, END = "<!-- showreel:start -->", "<!-- showreel:end -->"
BLOCK = f"""{START}
![Showreel (10 s): run.cmd, password, automatic query, autocomplete, periods, tooltip](docs/showreel.gif)

*10-second showreel: `run.cmd` → password → the dashboard queries by itself → project/reporter autocomplete (type, Tab) → switch period → hover for cumulative created / resolved / ratio.
The terminal part is drawn from the real console messages of `run.cmd`; the dashboard is the real UI recorded on `demo.cmd` dummy data (the numbers are made up).
Rebuild: `node tests/capture_showreel.cjs` then `uv run --no-project --with pillow python tests/build_showreel.py`.*
{END}"""


def upsert_readme() -> str:
    """Insert the showreel block under the QUICK START link, or replace it when it is already there (idempotent)."""
    text = README.read_text(encoding="utf-8")
    if START in text and END in text:
        head, rest = text.split(START, 1)
        _, tail = rest.split(END, 1)
        updated, action = head + BLOCK + tail, "updated"
    else:
        marker = "QUICK_START.md)"
        lines = text.split(chr(10))
        index = next((i for i, line in enumerate(lines) if marker in line), None)
        if index is None:
            raise SystemExit("README.md has no QUICK START link line to put the showreel under.")
        lines[index + 1:index + 1] = ["", BLOCK]
        updated, action = chr(10).join(lines), "inserted"
    if updated == text:
        return "unchanged"
    README.write_text(updated, encoding="utf-8")
    return action


def main():
    from PIL import Image  # only needed to build the GIF

    items = json.loads(TIMELINE.read_text(encoding="utf-8"))
    durations = scaled_durations(items)
    images = []
    for item in items:
        frame = Image.open(FRAMES / item["file"]).convert("RGB").resize((WIDTH, HEIGHT), Image.LANCZOS)
        images.append(frame.quantize(colors=COLORS, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    images[0].save(OUTPUT, save_all=True, append_images=images[1:], duration=durations, loop=0, optimize=True, disposal=1)
    print(f"{OUTPUT.relative_to(ROOT)}: {len(images)} frames, {sum(durations) / 1000:.2f} s, {OUTPUT.stat().st_size / 1024:.0f} KB")
    print("README.md:", upsert_readme())


if __name__ == "__main__":
    main()
