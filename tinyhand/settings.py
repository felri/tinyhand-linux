"""Settings window: choose and pin pointers, size, ink, sounds, and shortcut setup."""

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, Gtk, Pango  # noqa: E402

from . import assets  # noqa: E402
from .assets import LASER  # noqa: E402
from .config import MAX_PINNED, SIZE_RANGE  # noqa: E402

FADES = [(1.0, "1 second"), (2.0, "2 seconds"), (3.0, "3 seconds"), (5.0, "5 seconds"),
         (10.0, "10 seconds"), (0.0, "Never (until cleared)")]
INTERACT = [("alt", "Alt"), ("ctrl", "Ctrl"), ("shift", "Shift"), ("off", "Off")]

NIRI_BINDS = """binds {
    Ctrl+Alt+H hotkey-overlay-title="TinyHand: toggle pointer" { spawn "~/.local/bin/tinyhand" "toggle"; }
    Ctrl+Alt+X hotkey-overlay-title="TinyHand: clear drawing" { spawn "~/.local/bin/tinyhand" "clear"; }
}"""


class SettingsWindow(Gtk.ApplicationWindow):
    def __init__(self, ctl):
        super().__init__(application=ctl.app, title="TinyHand Settings")
        self.ctl = ctl
        self.config = ctl.config
        self.set_default_size(760, 720)
        self.add_css_class("th-settings")

        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18,
                       margin_top=20, margin_bottom=24, margin_start=24, margin_end=24)
        scroller.set_child(page)
        self.set_child(scroller)

        # header
        head = Gtk.Box(spacing=14)
        logo = Gtk.Picture.new_for_filename(str(assets.ICONS_DIR / "tinyhand.png"))
        logo.set_size_request(56, 56)
        logo.set_can_shrink(True)
        head.append(logo)
        titles = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
        t = Gtk.Label(label="TinyHand", xalign=0)
        t.add_css_class("title-1")
        titles.append(t)
        sub = Gtk.Label(label="A tiny hand on a stick that points at things on your screen.", xalign=0)
        sub.add_css_class("dim-label")
        titles.append(sub)
        head.append(titles)
        spacer = Gtk.Box(hexpand=True)
        head.append(spacer)
        self.toggle_btn = Gtk.Button(valign=Gtk.Align.CENTER)
        self.toggle_btn.add_css_class("suggested-action")
        self.toggle_btn.add_css_class("pill")
        self.toggle_btn.connect("clicked", lambda _b: (self.ctl.toggle(), self._sync_toggle()))
        head.append(self.toggle_btn)
        page.append(head)
        self._sync_toggle()

        # pointers
        page.append(self._heading("Pointer",
                                  f"Click a pointer to use it. Pin up to {MAX_PINNED} to the toolbar."))
        self.flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=8,
                                min_children_per_line=4, column_spacing=6, row_spacing=6, homogeneous=True)
        self.tiles = {}
        for style in assets.ALL_STYLES:
            self.flow.append(self._tile(style))
        page.append(self.flow)
        assets.thumbnails_async(assets.ALL_STYLES, self._thumb_ready)

        # look
        page.append(self._heading("Look", None))
        grid = self._grid()
        size = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, SIZE_RANGE[0], SIZE_RANGE[1], 0.005)
        size.set_draw_value(False)
        size.set_hexpand(True)
        size.set_value(self.config["pointer_size"])
        size.connect("value-changed", lambda s: self.config.set("pointer_size", round(s.get_value(), 3)))
        self._row(grid, 0, "Pointer size", size)
        self._row(grid, 1, "Shadow", self._switch("shadow"))
        page.append(grid)

        # drawing
        page.append(self._heading("Drawing", "Hold the mouse button and drag to draw."))
        grid = self._grid()
        self._row(grid, 0, "Ink colour", self._dropdown(
            "ink", [(k, t) for k, t, _ in assets.INK_CHOICES]))
        self._row(grid, 1, "Drawings fade after", self._dropdown("fade_seconds", FADES))
        page.append(grid)

        # sound
        page.append(self._heading("Sound", None))
        grid = self._grid()
        box = Gtk.Box(spacing=6)
        box.append(self._dropdown("tap_sound", assets.TAP_SOUNDS))
        play = Gtk.Button(icon_name="media-playback-start-symbolic", tooltip_text="Preview")
        play.connect("clicked", lambda _b: self.ctl.sound.play(self.config["tap_sound"]))
        box.append(play)
        self._row(grid, 0, "Tap sound", box)
        self._row(grid, 1, "Sound with hands", self._switch("hand_sound"))
        self._row(grid, 2, "Sound with laser dot", self._switch("laser_sound"))
        page.append(grid)

        # clicking for real
        page.append(self._heading(
            "Clicking for real",
            "While the pointer is on, clicks become taps and nothing underneath gets clicked. "
            "Hold this key to click, scroll and use menus normally."))
        grid = self._grid()
        self._row(grid, 0, "Hold to click for real", self._dropdown("interact_key", INTERACT))
        page.append(grid)

        # shortcuts
        page.append(self._heading(
            "Shortcuts",
            "While the pointer is on: Esc turns it off, Ctrl+Alt+X clears the drawing. "
            "To toggle from anywhere, add these lines to ~/.config/niri/config.kdl "
            "(other desktops: bind a shortcut to the same commands)."))
        code = Gtk.Label(label=NIRI_BINDS, xalign=0, selectable=True)
        code.add_css_class("monospace")
        code.add_css_class("th-code")
        page.append(code)
        copy = Gtk.Button(label="Copy", halign=Gtk.Align.START)
        copy.connect("clicked", lambda _b: Gdk.Display.get_default().get_clipboard().set(NIRI_BINDS))
        page.append(copy)

        reset = Gtk.Button(label="Reset all settings", halign=Gtk.Align.START, margin_top=8)
        reset.add_css_class("destructive-action")
        reset.connect("clicked", lambda _b: self.config.reset())
        page.append(reset)

        self.config.connect(self._on_config)
        self.connect("close-request", self._on_close)
        self._alive = True

    # ---- building blocks

    def _heading(self, title, text):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, margin_top=6)
        lbl = Gtk.Label(label=title, xalign=0)
        lbl.add_css_class("title-4")
        box.append(lbl)
        if text:
            d = Gtk.Label(label=text, xalign=0, wrap=True)
            d.add_css_class("dim-label")
            box.append(d)
        return box

    def _grid(self):
        g = Gtk.Grid(column_spacing=18, row_spacing=10)
        g.add_css_class("th-card")
        return g

    def _row(self, grid, row, label, widget):
        lbl = Gtk.Label(label=label, xalign=0, hexpand=False)
        lbl.set_size_request(200, -1)
        grid.attach(lbl, 0, row, 1, 1)
        widget.set_halign(Gtk.Align.FILL if isinstance(widget, Gtk.Scale) else Gtk.Align.START)
        grid.attach(widget, 1, row, 1, 1)

    def _switch(self, key):
        sw = Gtk.Switch(active=bool(self.config[key]), valign=Gtk.Align.CENTER)
        sw.connect("notify::active", lambda s, _p: self.config.set(key, s.get_active()))
        sw._th_key = key
        return sw

    def _dropdown(self, key, options):
        dd = Gtk.DropDown.new_from_strings([t for _, t in options])
        values = [v for v, _ in options]
        current = self.config[key]
        dd.set_selected(values.index(current) if current in values else 0)
        dd.connect("notify::selected", lambda d, _p: self.config.set(key, values[d.get_selected()]))
        return dd

    def _tile(self, style):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.add_css_class("th-tile")
        btn = Gtk.Button()
        btn.add_css_class("flat")
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        if style == LASER:
            pic = Gtk.Box(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
            pic.add_css_class("th-laser-dot")
            holder = Gtk.Box(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
            holder.set_size_request(64, 64)
            holder.append(pic)
            inner.append(holder)
        else:
            pic = Gtk.Picture(can_shrink=True, content_fit=Gtk.ContentFit.CONTAIN)
            pic.set_size_request(64, 64)
            inner.append(pic)
        lbl = Gtk.Label(label=assets.style_title(style), ellipsize=Pango.EllipsizeMode.END)
        lbl.add_css_class("caption")
        inner.append(lbl)
        btn.set_child(inner)
        btn.connect("clicked", lambda _b: self.ctl.pick(style))
        box.append(btn)
        pin = Gtk.CheckButton(label="Toolbar", tooltip_text="Pin to the toolbar", halign=Gtk.Align.CENTER)
        pin.add_css_class("caption")
        pin.set_active(style in self.config["pinned"])
        pin.connect("toggled", lambda b: self._pin(style, b))
        box.append(pin)
        self.tiles[style] = (box, pic, pin)
        self._sync_tile(style)
        return box

    def _thumb_ready(self, style, texture):
        if style in self.tiles:
            self.tiles[style][1].set_paintable(texture)

    def _pin(self, style, button):
        pinned = list(self.config["pinned"])
        if button.get_active() and style not in pinned:
            if len(pinned) >= MAX_PINNED:
                button.set_active(False)
                return
            pinned.append(style)
        elif not button.get_active() and style in pinned:
            if len(pinned) == 1:
                button.set_active(True)
                return
            pinned.remove(style)
        order = {s: i for i, s in enumerate(assets.ALL_STYLES)}
        self.config.set("pinned", sorted(pinned, key=lambda s: order.get(s, 999)))

    def _sync_tile(self, style):
        box, _pic, pin = self.tiles[style]
        if style == self.config["style"]:
            box.add_css_class("selected")
        else:
            box.remove_css_class("selected")
        want = style in self.config["pinned"]
        if pin.get_active() != want:
            pin.set_active(want)

    def _sync_toggle(self):
        self.toggle_btn.set_label("Turn pointer off" if self.ctl.active else "Turn pointer on")

    def _on_config(self, key):
        if not self._alive:
            return
        if key in (None, "style", "pinned"):
            for s in self.tiles:
                self._sync_tile(s)
        if key is None:  # reset: simplest is to rebuild the window
            self.ctl.reopen_settings()

    def _on_close(self, *_):
        self._alive = False
        return False
