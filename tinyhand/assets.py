"""Pointer styles, hand images and their measurements, thumbnails, tap sounds."""

import json
import threading
from pathlib import Path

import gi

gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib  # noqa: E402

from .config import CACHE_DIR  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent / "assets"
HANDS_DIR = ROOT / "hands"
SOUNDS_DIR = ROOT / "sounds"
ICONS_DIR = ROOT / "icons"

PURPLE = 0x8754F2
RED = 0xFF2A1F

# (id, title, ink colour), same order and names as the original app
HANDS = [
    ("lavender", "Lavender toy", PURPLE), ("glove", "Cursor glove", PURPLE),
    ("coral", "Coral vinyl", RED), ("plush", "Plush", 0x2F86F0),
    ("robot", "Robot", 0x16A87A), ("pink", "Bubblegum", 0xEE4F98),
    ("blue", "Sky", 0x2F86F0), ("mint", "Mint", 0x16A87A),
    ("lemon", "Lemon", 0xF2B705), ("black", "Midnight", 0x1D1D21),
    ("chrome", "Chrome", 0x6B7380), ("holo", "Holo", PURPLE),
    ("fuzzy", "Fuzzy", PURPLE), ("wood", "Wood", 0x9A5E2C),
    ("marble", "Marble", 0x6B7380), ("terrazzo", "Terrazzo", 0xF0561D),
    ("glass", "Glass", 0x1597E5), ("jelly", "Jelly", 0xA33FE6),
    ("pastel", "Pastel", 0xEE4F98), ("pixel", "Pixel", 0x1D1D21),
    ("lowpoly", "Low poly", PURPLE), ("knit", "Knit", PURPLE),
    ("skeleton", "Skeleton", 0x9A5E2C), ("astro", "Astronaut", 0x2F86F0),
    ("space", "Space", RED), ("monster", "Monster", 0x3E9E2E),
    ("water", "Water", 0x1597E5), ("lava", "Lava", 0xF0561D),
    ("grass", "Grass", 0x3E9E2E), ("cactus", "Cactus", 0x3E9E2E),
    ("choco", "Chocolate", 0x9A5E2C), ("cloud", "Cloud", 0x2F86F0),
    ("mech", "Mech", 0xF0561D), ("neon", "Neon", 0xE0309A),
    ("leaf", "Leaf", 0x3E9E2E), ("cookie", "Gingerbread", 0x9A5E2C),
]
LASER = "laser"
ALL_STYLES = [h[0] for h in HANDS] + [LASER]

INK_CHOICES = [
    ("match", "Match the pointer", None), ("red", "Red", RED),
    ("orange", "Orange", 0xFF8A00), ("yellow", "Yellow", 0xFFCC00),
    ("green", "Green", 0x30C25A), ("blue", "Blue", 0x0A84FF),
    ("purple", "Purple", PURPLE), ("white", "White", 0xFFFFFF),
    ("black", "Black", 0x1D1D21),
]

TAP_SOUNDS = [("thock", "Thock"), ("click", "Click"), ("pop", "Pop"),
              ("wood", "Wood block"), ("boop", "Boop"), ("squeak", "Squeak")]


def rgba(hex_value, alpha=1.0):
    c = Gdk.RGBA()
    c.red = ((hex_value >> 16) & 0xFF) / 255
    c.green = ((hex_value >> 8) & 0xFF) / 255
    c.blue = (hex_value & 0xFF) / 255
    c.alpha = alpha
    return c


def style_title(style):
    if style == LASER:
        return "Laser dot"
    return next((t for i, t, _ in HANDS if i == style), style)


def style_ink(style):
    if style == LASER:
        return RED
    return next((c for i, _, c in HANDS if i == style), PURPLE)


def ink_color(choice, style):
    value = next((c for i, _, c in INK_CHOICES if i == choice), None)
    return value if value is not None else style_ink(style)


def hand_path(style):
    return HANDS_DIR / f"hand_{style}.png"


# ---------------------------------------------------------------- measuring

_meta_lock = threading.Lock()
_meta_file = CACHE_DIR / "hands.json"
_meta = None


def _load_meta():
    global _meta
    if _meta is None:
        try:
            _meta = json.loads(_meta_file.read_text())
        except (OSError, ValueError):
            _meta = {}
    return _meta


def _measure(path):
    """Find the hand, wrist and stick in a hand image (port of HandAsset.measure)."""
    import numpy as np
    from PIL import Image

    with Image.open(path) as im:
        alpha = np.asarray(im.convert("RGBA").getchannel("A"))
    h, w = alpha.shape
    mask = alpha > 128
    counts = mask.sum(axis=1)
    rows = np.nonzero(counts)[0]
    if rows.size == 0:
        return None
    top = int(rows[0])
    last_row = int(rows[-1])
    search_end = min(h, top + int(0.45 * h))
    max_w = int(counts[top:search_end].max())
    if max_w <= 0:
        return None

    def first(start, cond):
        idx = np.nonzero(cond(counts[start:]))[0]
        return start + int(idx[0]) if idx.size else None

    fist = first(top, lambda c: c > 0.6 * max_w)
    if fist is None:
        return None
    wrist = first(fist, lambda c: c < 0.35 * max_w)
    if wrist is None:
        return None
    rod_w = int(counts[min(h - 1, wrist + h // 50)])
    handle = first(min(h - 1, wrist + h // 33), lambda c: c > 1.8 * rod_w)
    rod_end = handle if handle is not None else last_row

    def center(y):
        xs = np.nonzero(mask[y])[0]
        return 0.5 if xs.size == 0 else (int(xs[0]) + int(xs[-1])) / 2 / w

    cols = np.nonzero(mask[top:wrist].any(axis=0))[0]
    return {
        "w": w, "h": h,
        "aspect": w / h,
        "hand_top": max(0.0, top - 0.004 * h) / h,
        "tip": top / h,
        "wrist": wrist / h,
        "rod_end": rod_end / h,
        "tip_x": center(min(h - 1, top + h // 200)),
        "rod_x": center((wrist + rod_end) // 2),
        "hand_min_x": int(cols[0]) / w if cols.size else 0.0,
        "hand_max_x": int(cols[-1]) / w if cols.size else 1.0,
    }


def measure(style):
    path = hand_path(style)
    key = f"{style}:{int(path.stat().st_mtime)}"
    with _meta_lock:
        meta = _load_meta()
        if key in meta:
            return meta[key]
    m = _measure(path)
    if m is None:
        return None
    with _meta_lock:
        meta = _load_meta()
        meta[key] = m
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            _meta_file.write_text(json.dumps(meta))
        except OSError:
            pass
    return m


class HandAsset:
    def __init__(self, style, meta, texture):
        self.style = style
        self.texture = texture
        for k, v in meta.items():
            setattr(self, k, v)


_asset_cache = {}


def load_hand(style):
    """Texture plus measurements for a hand. Returns None for the laser or a broken file."""
    if style == LASER:
        return None
    if style in _asset_cache:
        return _asset_cache[style]
    path = hand_path(style)
    if not path.exists():
        return None
    meta = measure(style)
    if meta is None:
        return None
    asset = HandAsset(style, meta, Gdk.Texture.new_from_filename(str(path)))
    if len(_asset_cache) >= 3:
        _asset_cache.pop(next(iter(_asset_cache)))
    _asset_cache[style] = asset
    return asset


# ---------------------------------------------------------------- thumbnails

THUMB_DIR = CACHE_DIR / "thumbs"
_thumb_textures = {}


def _make_thumb(style):
    out = THUMB_DIR / f"{style}.png"
    src = hand_path(style)
    if out.exists() and out.stat().st_mtime >= src.stat().st_mtime:
        return out
    from PIL import Image

    m = measure(style)
    with Image.open(src) as im:
        im = im.convert("RGBA")
        w, h = im.size
        hand_w = (m["hand_max_x"] - m["hand_min_x"]) * w
        hand_h = (m["wrist"] - m["hand_top"]) * h
        side = max(hand_w, hand_h) * 1.06
        cx = (m["hand_min_x"] + m["hand_max_x"]) / 2 * w
        cy = (m["hand_top"] + m["wrist"]) / 2 * h
        box = (int(max(0, cx - side / 2)), int(max(0, cy - side / 2)),
               int(min(w, cx + side / 2)), int(min(h, cy + side / 2)))
        thumb = im.crop(box)
        thumb.thumbnail((128, 128), Image.LANCZOS)
        canvas = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
        canvas.paste(thumb, ((128 - thumb.width) // 2, (128 - thumb.height) // 2))
    THUMB_DIR.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp.png")
    canvas.save(tmp)
    tmp.replace(out)
    return out


def thumbnail(style):
    """A 128px Gdk.Texture of the hand alone (blocking; cached)."""
    if style in _thumb_textures:
        return _thumb_textures[style]
    try:
        tex = Gdk.Texture.new_from_filename(str(_make_thumb(style)))
    except Exception as e:  # broken image, missing PIL
        print(f"tinyhand: no thumbnail for {style}: {e}")
        return None
    _thumb_textures[style] = tex
    return tex


def thumbnails_async(styles, on_ready):
    """Build thumbnails in a thread, then call on_ready(style, texture) on the main loop."""
    todo = [s for s in styles if s != LASER]

    def work():
        for s in todo:
            try:
                path = _make_thumb(s)
            except Exception as e:
                print(f"tinyhand: no thumbnail for {s}: {e}")
                continue
            GLib.idle_add(_deliver, s, path)

    def _deliver(s, path):
        if s not in _thumb_textures:
            _thumb_textures[s] = Gdk.Texture.new_from_filename(str(path))
        on_ready(s, _thumb_textures[s])
        return False

    threading.Thread(target=work, daemon=True).start()
