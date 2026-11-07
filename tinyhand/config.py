"""Settings stored as JSON in ~/.config/tinyhand/config.json."""

import json
import os
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "tinyhand"
CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "tinyhand"
CONFIG_FILE = CONFIG_DIR / "config.json"

MAX_PINNED = 8
SIZE_RANGE = (0.08, 0.20)

DEFAULTS = {
    "style": "lavender",
    "pinned": ["lavender", "glove", "coral", "plush", "robot", "laser"],
    "pointer_size": 0.13,
    "shadow": True,
    "fade_seconds": 3.0,
    "hand_sound": True,
    "laser_sound": False,
    "tap_sound": "thock",
    "ink": "match",
    "interact_key": "alt",
    "hint_shown": False,
    "welcomed": False,
}


class Config:
    def __init__(self):
        self._data = dict(DEFAULTS)
        self._listeners = []
        try:
            with open(CONFIG_FILE) as f:
                stored = json.load(f)
            if isinstance(stored, dict):
                self._data.update({k: v for k, v in stored.items() if k in DEFAULTS})
        except (OSError, ValueError):
            pass

    def __getitem__(self, key):
        return self._data[key]

    def set(self, key, value):
        if self._data.get(key) == value:
            return
        self._data[key] = value
        self._save()
        for fn in list(self._listeners):
            fn(key)

    def reset(self):
        keep = {"hint_shown": self._data["hint_shown"], "welcomed": self._data["welcomed"]}
        self._data = dict(DEFAULTS, **keep)
        self._save()
        for fn in list(self._listeners):
            fn(None)

    def connect(self, fn):
        self._listeners.append(fn)

    def _save(self):
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            tmp = CONFIG_FILE.with_suffix(".tmp")
            with open(tmp, "w") as f:
                json.dump(self._data, f, indent=2)
            tmp.replace(CONFIG_FILE)
        except OSError as e:
            print(f"tinyhand: could not save settings: {e}")
