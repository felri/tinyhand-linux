"""TinyHand for Linux: application, commands and the on/off controller."""

import json
import subprocess
import sys
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

from . import assets  # noqa: E402
from .assets import LASER  # noqa: E402
from .config import Config  # noqa: E402
from .sound import TapSound  # noqa: E402

APP_ID = "io.github.tinyhand.Linux"
COMMANDS = ("toggle", "on", "off", "clear", "settings", "quit")

USAGE = """Usage: tinyhand [COMMAND]

Commands (sent to the running TinyHand, which is started if needed):
  toggle     Turn the pointer on or off
  on / off   Turn the pointer on / off
  clear      Clear the drawing
  settings   Open the settings window
  style NAME Switch pointer: lavender, glove, coral, ... or laser
  quit       Quit TinyHand

With no command, TinyHand starts in the background (tray icon) or,
if it is already running, opens its settings.
"""

CSS = """
window.th-overlay, window.th-overlay > * { background: transparent; }
.th-toolbar {
  background: rgba(28, 28, 31, 0.94);
  border-radius: 16px;
  padding: 6px;
  box-shadow: 0 6px 24px rgba(0,0,0,0.35), inset 0 0 0 1px rgba(255,255,255,0.08);
}
.th-tool {
  min-width: 40px; min-height: 40px; padding: 2px;
  border-radius: 10px; background: transparent; border: none; box-shadow: none;
  color: rgba(255,255,255,0.85);
}
menubutton.th-tool > button {
  min-width: 36px; min-height: 36px; padding: 2px; border-radius: 10px;
  background: transparent; border: none; box-shadow: none;
}
.th-tool:hover, menubutton.th-tool > button:hover, menubutton.th-tool > button:checked { background: rgba(255,255,255,0.10); }
.th-tool.selected { background: rgba(255,255,255,0.20); }
.th-sep { min-width: 1px; min-height: 24px; margin: 8px 4px; background: rgba(255,255,255,0.18); }
.th-laser-dot {
  min-width: 14px; min-height: 14px; border-radius: 99px;
  background: #ff2a1f; box-shadow: 0 0 10px 2px rgba(255,42,31,0.8);
}
.th-swatch {
  min-width: 18px; min-height: 18px; border-radius: 99px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.5), inset 0 0 0 1px rgba(255,255,255,0.25);
}
.th-swatch.ink-match { background: conic-gradient(#ff2a1f, #ff8a00, #ffcc00, #30c25a, #0a84ff, #8754f2, #ff2a1f); }
.th-swatch.ink-red { background: #ff2a1f; }
.th-swatch.ink-orange { background: #ff8a00; }
.th-swatch.ink-yellow { background: #ffcc00; }
.th-swatch.ink-green { background: #30c25a; }
.th-swatch.ink-blue { background: #0a84ff; }
.th-swatch.ink-purple { background: #8754f2; }
.th-swatch.ink-white { background: #ffffff; }
.th-swatch.ink-black { background: #1d1d21; }
popover.th-popover > contents { background: rgba(28,28,31,0.96); border-radius: 14px; padding: 6px; }
.th-hint {
  background: rgba(28, 28, 31, 0.94); color: rgba(255,255,255,0.75);
  border-radius: 12px; padding: 9px 16px;
}
.th-hint b { color: white; }
.th-card { padding: 14px 16px; border-radius: 12px; background: alpha(currentColor, 0.05); }
.th-tile { border-radius: 12px; padding: 4px; }
.th-tile.selected { background: rgba(135, 84, 242, 0.22); box-shadow: inset 0 0 0 2px #8754f2; }
.th-code { padding: 12px 14px; border-radius: 10px; background: alpha(currentColor, 0.07); }
"""


def _focused_output():
    """niri knows which monitor has focus; other compositors fall back to the first monitor."""
    try:
        out = subprocess.run(["niri", "msg", "--json", "focused-output"], capture_output=True,
                             text=True, timeout=0.5)
        return (json.loads(out.stdout) or {}).get("name")
    except (OSError, ValueError, subprocess.SubprocessError, AttributeError):
        return None


class Controller:
    def __init__(self, app):
        self.app = app
        self.config = Config()
        self.sound = TapSound()
        self.windows = []
        self.active = False
        self.reveal_until = 0.0
        self.passthrough = False
        self.focus_window = None
        self.settings_window = None
        self.tray = None
        self.asset = None
        self.style = self.config["style"]
        self._load_style()
        self.config.connect(self._on_config)
        self._monitors = None

    # ---- style

    def _load_style(self):
        self.style = self.config["style"] if self.config["style"] in assets.ALL_STYLES else "lavender"
        self.asset = assets.load_hand(self.style)
        if self.asset is None and self.style != LASER:
            self.style = LASER

    def pick(self, style):
        self.config.set("style", style)

    @property
    def sound_on(self):
        return self.config["laser_sound"] if self.style == LASER else self.config["hand_sound"]

    def toggle_sound(self):
        self.config.set("laser_sound" if self.style == LASER else "hand_sound", not self.sound_on)

    def tapped(self):
        if self.sound_on:
            self.sound.play(self.config["tap_sound"])

    def _on_config(self, key):
        if key in (None, "style"):
            self._load_style()
        for w in self.windows:
            if key in (None, "pinned"):
                w.toolbar.rebuild()
            else:
                w.toolbar.sync()
            w.canvas.queue_draw()
        if key in (None, "tap_sound"):
            self.sound.warm(self.config["tap_sound"])

    # ---- on / off

    def toggle(self):
        if self.active:
            self.deactivate()
        else:
            self.activate()

    def activate(self):
        if self.active:
            return
        self.active = True
        self.passthrough = False
        self.sound.warm(self.config["tap_sound"])
        display = Gdk.Display.get_default()
        self._monitors = display.get_monitors()
        self._monitors_handler = self._monitors.connect("items-changed", self._on_monitors_changed)
        self._build_windows()
        self.reveal_until = time.monotonic() + 3
        if not self.config["hint_shown"]:
            self.config.set("hint_shown", True)
            parts = [("Click", "to tap"), ("Drag", "to draw")]
            from .overlay import INTERACT_KEYS
            key = INTERACT_KEYS.get(self.config["interact_key"])
            if key:
                parts.append((f"Hold {key[1]}", "to click for real"))
            parts.append(("Esc", "to exit"))
            for w in self.windows:
                w.toolbar.show_hint(parts)
            self.reveal_until = time.monotonic() + 10
            GLib.timeout_add_seconds(10, self._hide_hints)
        GLib.timeout_add(int((self.reveal_until - time.monotonic()) * 1000) + 50, self._refresh_reveal)
        self._changed()

    def _build_windows(self):
        from .overlay import OverlayWindow

        for w in self.windows:
            w.destroy()
        self.windows = []
        focused = _focused_output()
        for i in range(self._monitors.get_n_items()):
            mon = self._monitors.get_item(i)
            win = OverlayWindow(self, mon)
            win.present()
            win.toolbar.revealer.set_reveal_child(True)
            self.windows.append(win)
        target = next((w for w in self.windows if w.monitor.get_connector() == focused), None)
        self.pointer_entered(target or (self.windows[0] if self.windows else None))

    def _on_monitors_changed(self, *_):
        if self.active:
            GLib.timeout_add(300, lambda: self.active and self._build_windows() and False)

    def _hide_hints(self):
        for w in self.windows:
            w.toolbar.hide_hint()
        return False

    def _refresh_reveal(self):
        for w in self.windows:
            w.update_toolbar_reveal()
        return False

    def pointer_entered(self, window):
        if window is None or window is self.focus_window:
            return
        self.focus_window = window
        for w in self.windows:
            if w is not window:
                w.canvas.leave()
        for w in self.windows:
            w.set_keyboard(w is window)

    def deactivate(self):
        if not self.active:
            return
        self.active = False
        if self._monitors is not None:
            self._monitors.disconnect(self._monitors_handler)
            self._monitors = None
        for w in self.windows:
            w.destroy()
        self.windows = []
        self.focus_window = None
        self.passthrough = False
        self._changed()

    def exit(self):
        self.clear()
        self.deactivate()

    def clear(self):
        for w in self.windows:
            w.canvas.clear_ink()

    def set_passthrough(self, on):
        if on == self.passthrough:
            return
        self.passthrough = on
        for w in self.windows:
            w.set_passthrough(on)

    def _changed(self):
        if self.tray:
            self.tray.update()
        if self.settings_window is not None:
            self.settings_window._sync_toggle()

    # ---- windows

    def open_settings(self):
        from .settings import SettingsWindow

        if self.settings_window is None:
            self.settings_window = SettingsWindow(self)
            self.settings_window.connect("destroy", self._settings_closed)
        if self.active:
            self.deactivate()  # the overlay would sit on top of the settings window
        self.settings_window.present()

    def reopen_settings(self):
        if self.settings_window is not None:
            old = self.settings_window
            self.settings_window = None
            GLib.idle_add(lambda: (old.destroy(), self.open_settings()) and False)

    def _settings_closed(self, win):
        if self.settings_window is win:
            self.settings_window = None

    def quit(self):
        self.deactivate()
        self.sound.stop_all()
        self.app.quit()


class TinyHandApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.ctl = None

    def do_startup(self):
        Gtk.Application.do_startup(self)
        provider = Gtk.CssProvider()
        provider.load_from_string(CSS)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.ctl = Controller(self)
        for name in COMMANDS:
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda _a, _p, n=name: self.run_command(n))
            self.add_action(action)
        style = Gio.SimpleAction.new("style", GLib.VariantType.new("s"))
        style.connect("activate", lambda _a, p: self.set_style(p.get_string()))
        self.add_action(style)
        self.hold()  # keep running in the background with no windows
        from .tray import Tray

        self.ctl.tray = Tray(self.ctl)
        assets.thumbnails_async(self.ctl.config["pinned"], lambda *_: None)

    def run_command(self, name):
        ctl = self.ctl
        {"toggle": ctl.toggle, "on": ctl.activate, "off": ctl.deactivate, "clear": ctl.clear,
         "settings": ctl.open_settings, "quit": ctl.quit}[name]()

    def set_style(self, name):
        if name in assets.ALL_STYLES:
            self.ctl.pick(name)
            return True
        return False

    def do_command_line(self, cmdline):
        args = cmdline.get_arguments()[1:]
        if args and args[0] in ("-h", "--help", "help"):
            cmdline.print_literal(USAGE)
            return 0
        if args and args[0] == "style":
            if len(args) < 2 or not self.set_style(args[1]):
                cmdline.printerr_literal("tinyhand: style needs one of: " + ", ".join(assets.ALL_STYLES) + "\n")
                return 2
            return 0
        if args and args[0] not in COMMANDS:
            cmdline.printerr_literal(f"tinyhand: unknown command '{args[0]}'\n\n{USAGE}")
            return 2
        if args:
            self.run_command(args[0])
        elif cmdline.get_is_remote() or not self.ctl.config["welcomed"]:
            # launched again (or for the first time): show settings, like the macOS app's welcome
            self.ctl.config.set("welcomed", True)
            self.ctl.open_settings()
        else:
            print("TinyHand is running. Use the tray icon, or run: tinyhand toggle")
        return 0

    def do_activate(self):
        pass


def main():
    app = TinyHandApp()
    return app.run(sys.argv)
