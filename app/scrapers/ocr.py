"""Read a menu that is posted as a picture.

Tesseract finds the words and their positions. Lines are rebuilt from those
positions instead of Tesseract's own blocks, because menus are laid out as
tables: a narrow number column, the dish, and a price far to the right. Two-
column pages (e.g. Monday-Wednesday left, Thursday-Friday right) are split at
the empty vertical gap between the columns.
"""
from __future__ import annotations

import csv
import hashlib
import io
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
from statistics import median

log = logging.getLogger(__name__)

LANGS = "ces+eng"
_cache: dict[str, list[str]] = {}
# One OCR at a time: parallel Tesseract runs (each multi-threaded) starve each other.
_lock = threading.Lock()


def available() -> bool:
    return shutil.which("tesseract") is not None


def _prepare(data: bytes) -> tuple[bytes, int]:
    from PIL import Image  # imported lazily: only needed for pictures

    im = Image.open(io.BytesIO(data))
    im = im.convert("L")
    # Small print reads much better at roughly 2x the size menus are usually posted at.
    scale = 2 if im.width < 2000 else 1
    if scale > 1:
        im = im.resize((im.width * scale, im.height * scale), Image.LANCZOS)
    out = io.BytesIO()
    im.save(out, format="PNG")
    return out.getvalue(), im.width


def _words(png: bytes) -> list[dict]:
    with tempfile.NamedTemporaryFile(suffix=".png") as f:
        f.write(png)
        f.flush()
        proc = subprocess.run(
            ["tesseract", f.name, "-", "-l", LANGS, "--psm", "3", "tsv"],
            capture_output=True, text=True, timeout=180,
            env={**os.environ, "OMP_THREAD_LIMIT": "1"},
        )
    words = []
    for r in csv.DictReader(io.StringIO(proc.stdout), delimiter="\t", quoting=csv.QUOTE_NONE):
        text = (r.get("text") or "").strip()
        if r.get("level") == "5" and text and float(r.get("conf") or -1) >= 0:
            words.append({"x": int(r["left"]), "y": int(r["top"]), "w": int(r["width"]),
                          "h": int(r["height"]), "t": text})
    return words


def _gutter(words: list[dict], width: int) -> int | None:
    """x of an empty vertical strip in the middle of the page, if the page has two columns."""
    cover = [0] * (width + 1)
    for w in words:
        for x in range(max(0, w["x"]), min(width, w["x"] + w["w"])):
            cover[x] += 1
    best, start = (0, 0), None
    for x in range(int(width * 0.3), int(width * 0.7)):
        if cover[x] == 0:
            start = x if start is None else start
            if x - start > best[1] - best[0]:
                best = (start, x)
        else:
            start = None
    if best[1] - best[0] >= width * 0.008:
        return (best[0] + best[1]) // 2
    return None


def _rows(words: list[dict]) -> list[str]:
    if not words:
        return []
    line_h = median(w["h"] for w in words)
    rows: list[list[dict]] = []
    for w in sorted(words, key=lambda w: w["y"] + w["h"] / 2):
        yc = w["y"] + w["h"] / 2
        if rows:
            last = rows[-1]
            lc = median(x["y"] + x["h"] / 2 for x in last)
            if abs(yc - lc) <= line_h * 0.6:
                last.append(w)
                continue
        rows.append([w])
    return [" ".join(w["t"] for w in sorted(r, key=lambda w: w["x"])) for r in rows]


KC_FIX = re.compile(r"(\d)\s*(?:K[EČCcčeé€]|k[čcé]|Ké)(?![a-zá-ž])")


def normalize(line: str) -> str:
    line = KC_FIX.sub(r"\1 Kč", line)
    line = re.sub(r"\s+", " ", line).strip()
    # bullet in front of a dish ("* Tomato Soup"), not the *** of a note line
    line = re.sub(r"^[*•·]\s+(?=\w)", "", line)
    return line


def lines_from_image(data: bytes) -> list[str]:
    """Text lines of a menu picture, column by column. Empty if OCR is unavailable."""
    if not available():
        return []
    key = hashlib.sha256(data).hexdigest()
    with _lock:
        if key in _cache:
            return _cache[key]
        try:
            png, width = _prepare(data)
            words = _words(png)
        except Exception:
            log.exception("OCR failed")
            return []
        lines = _lines(words, width)
        _cache[key] = lines
        return lines


def _lines(words: list[dict], width: int) -> list[str]:
    gutter = _gutter(words, width)
    columns = [words] if gutter is None else [
        [w for w in words if w["x"] + w["w"] / 2 < gutter],
        [w for w in words if w["x"] + w["w"] / 2 >= gutter],
    ]
    lines = [normalize(l) for col in columns for l in _rows(col)]
    return [l for l in lines if l]
