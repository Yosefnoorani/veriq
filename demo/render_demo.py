"""Render docs/assets/veriq_demo.gif (+ a PNG still) from REAL command output.

    .venv/bin/python demo/render_demo.py

Every command shown in the GIF is actually executed (from examples/transpile_hazard,
with the repo venv on PATH) and its captured stdout/stderr is what gets drawn. Only the
typing animation, colours and timing are synthetic. Needs Pillow and DejaVu Sans Mono.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
WORKDIR = ROOT / "examples" / "transpile_hazard"
OUT_GIF = ROOT / "docs" / "assets" / "veriq_demo.gif"
OUT_PNG = ROOT / "docs" / "assets" / "veriq_demo.png"
FONT_PATHS = ["/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
              "/System/Library/Fonts/Menlo.ttc", "C:/Windows/Fonts/consola.ttf"]
BOLD_PATHS = ["/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"] + FONT_PATHS

COLS, ROWS, SIZE, PAD = 122, 34, 14, 16
BG, FG, DIM = (22, 24, 33), (220, 223, 228), (128, 134, 150)
GREEN, RED, YELLOW, BLUE, PURPLE = (80, 200, 120), (240, 90, 90), (230, 190, 80), (110, 170, 250), (180, 140, 250)

# (kind, text): "note" = a comment typed at the prompt, "cmd" = a command that is executed
SCRIPT = [
    ("note", "# compiled.py = transpile(block) with Qiskit defaults; block = mcx([0,1,2], 3) on 5 qubits"),
    ("note", "# 1) the usual test: sample both on Aer from |0...0> and compare histograms"),
    ("cmd", "pytest -q test_histogram.py"),
    ("note", "# 2) Veriq: prove equivalence, find a counterexample, localise the bug"),
    ("cmd", "veriq check compiled.py -r block.py --repair-report bug.json"),
    ("cmd", "jq -r '.hints[]' bug.json"),
    ("cmd", "jq -r '.localization.regions[0] | \"bug region: gates #\\(.gate_start)..#\\(.gate_end) on qubits \\(.support)\"' bug.json"),
    ("note", "# the compiled block borrowed idle q4 as a |0> ancilla: wrong once reused via to_gate()"),
    ("note", "# 3) the fix: transpile(..., qubits_initially_zero=False)"),
    ("cmd", "veriq check compiled.py -f build_safe -r block.py"),
]

ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _font(paths, size):
    for p in paths:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    raise SystemExit("no monospace font found")


def run(cmd: str) -> str:
    env = dict(os.environ)
    env["PATH"] = str(ROOT / ".venv" / "bin") + os.pathsep + env.get("PATH", "")
    env["PYTEST_ADDOPTS"] = "-p no:cacheprovider"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["COLUMNS"] = str(COLS)
    p = subprocess.run(cmd, shell=True, cwd=WORKDIR, env=env, capture_output=True, text=True, timeout=300)
    out = ANSI.sub("", p.stdout + p.stderr).rstrip("\n")
    return out


def colour(line: str) -> tuple:
    if line.startswith("#"):
        return DIM
    if "✘" in line or "VERDICT: FAIL" in line:
        return RED
    if "✔" in line or "VERDICT: PASS" in line or re.search(r"\d+ passed", line):
        return GREEN
    if line.startswith("Veriq "):
        return PURPLE
    if line.startswith(("On input", "No single", "bug region")):
        return YELLOW
    return FG


class Term:
    def __init__(self):
        self.font, self.bold = _font(FONT_PATHS, SIZE), _font(BOLD_PATHS, SIZE)
        box = self.font.getbbox("M")
        self.cw = self.font.getlength("M")
        self.ch = int((box[3] - box[1]) * 1.55) + 2
        self.w = int(PAD * 2 + self.cw * COLS)
        self.h = PAD * 2 + 30 + self.ch * ROWS
        self.lines: list[tuple[str, tuple, bool]] = []  # (text, colour, is_prompt)
        self.frames: list[tuple[Image.Image, int]] = []

    def push(self, text: str, col: tuple, prompt: bool = False):
        for chunk in (textwrap.wrap(text, COLS - (2 if prompt else 0), subsequent_indent="    ",
                                    drop_whitespace=False) or [""]):
            self.lines.append((chunk, col, prompt))
            prompt = False

    def render(self, cursor: bool = False) -> Image.Image:
        img = Image.new("RGB", (self.w, self.h), BG)
        d = ImageDraw.Draw(img)
        d.rectangle([0, 0, self.w, 30], fill=(40, 43, 56))
        for i, c in enumerate([(240, 90, 90), (230, 190, 80), (80, 200, 120)]):
            d.ellipse([14 + 22 * i, 9, 26 + 22 * i, 21], fill=c)
        d.text((self.w / 2, 15), "veriq: a circuit that passes the histogram test but is wrong",
               font=self.font, fill=DIM, anchor="mm")
        rows = []
        for text, col, prompt in self.lines:
            width = COLS - 2 if prompt else COLS
            parts = [text[i:i + width] for i in range(0, len(text), width)] or [""]
            rows.append((parts[0], col, prompt))
            rows.extend(("  " + p if prompt else p, col, False) for p in parts[1:])
        vis = rows[-ROWS:]
        y = 30 + PAD
        for i, (text, col, prompt) in enumerate(vis):
            x = PAD
            if prompt:
                d.text((x, y), "$ ", font=self.bold, fill=BLUE)
                x += self.cw * 2
            d.text((x, y), text, font=self.bold if prompt and not text.startswith("#") else self.font, fill=col)
            if cursor and i == len(vis) - 1:
                cx = x + self.cw * len(text)
                d.rectangle([cx + 1, y + 1, cx + self.cw - 1, y + self.ch - 4], fill=FG)
            y += self.ch
        return img

    def frame(self, ms: int, cursor: bool = False):
        self.frames.append((self.render(cursor), ms))


def main() -> int:
    t = Term()
    t.frame(900, cursor=True)
    for kind, text in SCRIPT:
        t.lines.append(("", FG, True))
        step = 3 if kind == "note" else 2
        for n in range(step, len(text) + step, step):
            typed = text[:n]
            t.lines[-1] = (typed, DIM if kind == "note" else FG, True)
            t.frame(28, cursor=True)
        if kind == "note":
            t.frame(900)
            continue
        t.frame(350)
        out = run(text)
        print(f"$ {text}\n{out}\n", file=sys.stderr)
        for line in out.splitlines():
            t.push(line, colour(line))
        t.frame(3200 if "veriq check compiled.py -r" in text else 2200)
    t.lines.append(("", FG, True))
    t.frame(4500, cursor=True)
    (WORKDIR / "bug.json").unlink(missing_ok=True)
    OUT_GIF.parent.mkdir(parents=True, exist_ok=True)
    imgs = [f.quantize(colors=32, method=Image.Quantize.MEDIANCUT) for f, _ in t.frames]
    imgs[0].save(OUT_GIF, save_all=True, append_images=imgs[1:], duration=[ms for _, ms in t.frames],
                 loop=0, optimize=True, disposal=1)
    t.frames[-1][0].save(OUT_PNG, optimize=True)
    total = sum(ms for _, ms in t.frames) / 1000
    print(f"wrote {OUT_GIF.relative_to(ROOT)} ({OUT_GIF.stat().st_size/1e6:.2f} MB, {len(t.frames)} frames, "
          f"{total:.1f} s) and {OUT_PNG.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
