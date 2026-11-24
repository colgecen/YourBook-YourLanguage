#!/usr/bin/env python3
"""Capture the real GUI and wrap it in a macOS-style SVG window frame.

Run from the repository root: python scripts/make_screenshots.py
Output: docs/img/app-gui.svg
"""

from __future__ import annotations

import base64
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "docs" / "img"
OUT_SVG = OUT_DIR / "app-gui.svg"
DEMO_INPUT = ROOT / "input" / "english-book.pdf"
DEMO_OUTPUT = ROOT / "output" / "screenshot-demo_tr.pdf"
LOG_FILE = Path(tempfile.gettempdir()) / "yourbook-screenshot.log"
PNG_FILE = Path(tempfile.gettempdir()) / "yourbook-screenshot.png"

MARGIN = 12
TITLE_H = 38


def make_demo_pdf() -> None:
    """Create a small English PDF for the interface preview."""
    import pymupdf

    doc = pymupdf.open()
    body = (
        "The morning was quiet, and the old library smelled of dust and rain. "
        "Elena placed the leather-bound book on the table and opened it carefully. "
        "She had been searching for this volume for years."
    )
    for number in range(1, 13):
        page = doc.new_page(width=595, height=842)
        page.insert_text(
            (55, 80),
            "The Old Sea-dog at the Admiral Benbow",
            fontname="Times-Bold",
            fontsize=17,
        )
        page.insert_text((55, 120), f"Chapter {number}", fontname="Times-Roman", fontsize=11)
        page.insert_textbox(
            pymupdf.Rect(55, 150, 540, 760),
            "\n\n".join([body] * 4),
            fontname="Times-Roman",
            fontsize=12,
            lineheight=1.5,
        )
        page.insert_text(
            (55, 810),
            f"YourBook YourLanguage  ·  Page {number}/12",
            fontname="Times-Roman",
            fontsize=9,
        )
    DEMO_INPUT.parent.mkdir(parents=True, exist_ok=True)
    doc.save(DEMO_INPUT)
    doc.close()


def capture_window() -> Path:
    """Open the English GUI, read its window id and capture the client area."""
    import_bin = shutil.which("import")
    if not import_bin:
        raise SystemExit("ImageMagick 'import' is required to capture the window.")
    if not os.environ.get("DISPLAY"):
        raise SystemExit("A graphical display is required to capture the window.")
    if LOG_FILE.exists():
        LOG_FILE.unlink()
    cmd = [
        sys.executable,
        str(ROOT / "gui.py"),
        "--input",
        str(DEMO_INPUT.relative_to(ROOT)),
        "--output",
        str(DEMO_OUTPUT.relative_to(ROOT)),
        "--lang",
        "en",
        "--print-window-id",
    ]
    with LOG_FILE.open("w", encoding="utf-8") as log:
        proc = subprocess.Popen(
            cmd,
            cwd=ROOT,
            stdout=log,
            stderr=subprocess.STDOUT,
            env=os.environ.copy(),
        )
    window_id = None
    for _ in range(150):
        if proc.poll() is not None:
            break
        try:
            match = re.search(r"WINDOW_ID\s+(\d+)", LOG_FILE.read_text(encoding="utf-8"))
        except OSError:
            match = None
        if match:
            window_id = match.group(1)
            break
        time.sleep(0.1)
    if not window_id:
        proc.terminate()
        raise SystemExit(f"Could not find the GUI window. See {LOG_FILE}.")
    time.sleep(1.2)
    subprocess.run([import_bin, "-window", window_id, str(PNG_FILE)], check=True)
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    return PNG_FILE


def build_svg(png_path: Path) -> str:
    """Embed the captured client area in a rounded macOS-style frame."""
    from PIL import Image

    with Image.open(png_path) as image:
        rgb = image.convert("RGB")
        width, height = rgb.size
        # The demo has an empty log panel; remove the mouse pointer from that area.
        pixels = rgb.load()
        for y in range(int(height * 0.72), int(height * 0.97)):
            for x in range(int(width * 0.04), int(width * 0.96)):
                r, g, b = pixels[x, y]
                if r > 100 and r > g * 1.25 and r > b * 1.25:
                    pixels[x, y] = (15, 23, 42)
        rgb.save(png_path)
    encoded = base64.b64encode(png_path.read_bytes()).decode("ascii")
    window_h = height + TITLE_H
    svg_w = width + MARGIN * 2
    svg_h = window_h + MARGIN * 2
    title = "YourBook YourLanguage"
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{svg_w}" height="{svg_h}" viewBox="0 0 {svg_w} {svg_h}">
  <defs>
    <clipPath id="window-clip">
      <rect x="{MARGIN}" y="{MARGIN}" width="{width}" height="{window_h}" rx="12"/>
    </clipPath>
  </defs>
  <g clip-path="url(#window-clip)">
    <rect x="{MARGIN}" y="{MARGIN}" width="{width}" height="{window_h}" fill="#0f172a"/>
    <rect x="{MARGIN}" y="{MARGIN}" width="{width}" height="{TITLE_H}" fill="#1f2937"/>
    <rect x="{MARGIN}" y="{MARGIN + TITLE_H - 12}" width="{width}" height="12" fill="#1f2937"/>
    <image x="{MARGIN}" y="{MARGIN + TITLE_H}" width="{width}" height="{height}"
           href="data:image/png;base64,{encoded}" preserveAspectRatio="xMidYMid meet"/>
  </g>
  <rect x="{MARGIN}" y="{MARGIN}" width="{width}" height="{window_h}" rx="12"
        fill="none" stroke="#334155" stroke-width="1"/>
  <circle cx="{MARGIN + 20}" cy="{MARGIN + 19}" r="6" fill="#ff5f57"/>
  <circle cx="{MARGIN + 40}" cy="{MARGIN + 19}" r="6" fill="#febc2e"/>
  <circle cx="{MARGIN + 60}" cy="{MARGIN + 19}" r="6" fill="#28c840"/>
  <text x="{MARGIN + width / 2}" y="{MARGIN + 24}" text-anchor="middle"
        font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"
        font-size="13" font-weight="600" fill="#e5e7eb">{title}</text>
</svg>
"""


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    make_demo_pdf()
    try:
        png = capture_window()
        OUT_SVG.write_text(build_svg(png), encoding="utf-8")
        print(OUT_SVG)
    finally:
        DEMO_INPUT.unlink(missing_ok=True)
        DEMO_OUTPUT.unlink(missing_ok=True)
        Path(f"{DEMO_OUTPUT}.checkpoint.json").unlink(missing_ok=True)
        LOG_FILE.unlink(missing_ok=True)
        PNG_FILE.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
