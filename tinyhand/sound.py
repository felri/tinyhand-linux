"""Short tap sounds through GStreamer, with pw-play as a fallback."""

import shutil
import subprocess

from .assets import SOUNDS_DIR

try:
    import gi

    gi.require_version("Gst", "1.0")
    from gi.repository import Gst

    Gst.init([])
except (ImportError, ValueError):
    Gst = None


class TapSound:
    def __init__(self):
        self._players = {}
        self._fallback = shutil.which("pw-play") or shutil.which("paplay")

    def _player(self, name):
        if name in self._players:
            return self._players[name]
        path = SOUNDS_DIR / f"tap_{name}.wav"
        if Gst is None or not path.exists():
            return None
        p = Gst.ElementFactory.make("playbin", None)
        if p is None:
            return None
        p.set_property("uri", path.as_uri())
        p.set_state(Gst.State.PAUSED)  # preroll so the first tap is quick
        self._players[name] = p
        return p

    def warm(self, name):
        self._player(name)

    def play(self, name):
        p = self._player(name)
        if p is not None:
            p.seek_simple(Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.ACCURATE, 0)
            p.set_state(Gst.State.PLAYING)
            return
        path = SOUNDS_DIR / f"tap_{name}.wav"
        if self._fallback and path.exists():
            subprocess.Popen([self._fallback, str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def stop_all(self):
        for p in self._players.values():
            p.set_state(Gst.State.NULL)
        self._players.clear()
