"""Full-screen layer-shell overlay: the hand on a stick, the laser dot, ink and the toolbar."""

import math
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Gsk", "4.0")
gi.require_version("Graphene", "1.0")
gi.require_version("Gtk4LayerShell", "1.0")
gi.require_foreign("cairo")
import cairo  # noqa: E402
from gi.repository import Gdk, GLib, Graphene, Gsk, Gtk  # noqa: E402
from gi.repository import Gtk4LayerShell as LayerShell  # noqa: E402

from . import assets  # noqa: E402
from .assets import LASER  # noqa: E402

# Geometry, all as fractions of the screen (same numbers as the macOS app)
GRIP_LEAN = 0.30      # grip sits this far right of the cursor (fraction of width)
GRIP_DEPTH = 0.12     # grip sits this far below the bottom edge (fraction of height)
GRIP_FOLLOW = 0.08    # per 1/120 s easing of the grip towards its target
MIN_ROD = 0.05
LIFT = 0.06           # shadow offset that makes the hand float above the screen
PRESS_DECAY = 0.18    # per 1/120 s
DRAG_START = 4        # px of movement before a press becomes a drawing

INTERACT_KEYS = {
    "alt": ({Gdk.KEY_Alt_L, Gdk.KEY_Alt_R, Gdk.KEY_Meta_L, Gdk.KEY_Meta_R}, "Alt"),
    "ctrl": ({Gdk.KEY_Control_L, Gdk.KEY_Control_R}, "Ctrl"),
    "shift": ({Gdk.KEY_Shift_L, Gdk.KEY_Shift_R}, "Shift"),
}


def _rect(x, y, w, h):
    return Graphene.Rect().init(x, y, w, h)


def _point(x, y):
    return Graphene.Point().init(x, y)


def _ease(factor, dt):
    """Turn a per-1/120s easing factor into one for an arbitrary frame time."""
    return 1 - (1 - factor) ** max(0.0, dt * 120)


_SHADOW_MATRIX = None


def _shadow_matrix():
    global _SHADOW_MATRIX
    if _SHADOW_MATRIX is None:
        _SHADOW_MATRIX = Graphene.Matrix().init_from_float([0] * 15 + [1])
    return _SHADOW_MATRIX


class Stroke:
    def __init__(self, x, y, color, width):
        self.points = [(x, y)]
        self.color = color
        self.width = width
        self.ended_at = None
        self.path = None

    def extend(self, x, y):
        lx, ly = self.points[-1]
        if math.hypot(x - lx, y - ly) < 1.5:
            return False
        self.points.append((x, y))
        self.path = None
        return True

    def build(self):
        if self.path is None:
            b = Gsk.PathBuilder.new()
            pts = self.points
            b.move_to(*pts[0])
            if len(pts) == 1:
                b.line_to(pts[0][0] + 0.01, pts[0][1])
            for (px, py), (x, y) in zip(pts, pts[1:]):
                b.quad_to(px, py, (px + x) / 2, (py + y) / 2)
            if len(pts) > 1:
                b.line_to(*pts[-1])
            self.path = b.to_path()
        return self.path

    def opacity(self, now, fade_seconds):
        if self.ended_at is None or fade_seconds <= 0:
            return 1.0
        t = now - self.ended_at - max(0.5, fade_seconds)
        if t <= 0:
            return 1.0
        if t >= 0.6:
            return 0.0
        return 1.0 - (t / 0.6) ** 2


class Canvas(Gtk.Widget):
    """Draws ink, then the hand (or laser) on top, for one monitor."""

    def __init__(self, ctl):
        super().__init__()
        self.ctl = ctl
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.cursor = None          # (x, y) in widget coordinates, None when the pointer is elsewhere
        self.pointer_hidden = False
        self.held = False
        self.press = 0.0
        self.grip_x = None
        self.grip_target = None
        self.strokes = []
        self.current = None
        self._tick_id = 0
        self._last_frame = None

    # ---- animation

    def wake(self):
        if not self._tick_id:
            self._last_frame = None
            self._tick_id = self.add_tick_callback(self._on_tick)
        self.queue_draw()

    def _on_tick(self, _widget, clock):
        now = clock.get_frame_time() / 1e6
        dt = 1 / 60 if self._last_frame is None else min(0.1, now - self._last_frame)
        self._last_frame = now
        if not self.held:
            self.press *= 1 - _ease(PRESS_DECAY, dt)
            if self.press < 0.002:
                self.press = 0.0
        if self.cursor is not None:
            target = self._grip_target(self.cursor[0])
            self.grip_target = target
            if self.grip_x is None:
                self.grip_x = target
            else:
                self.grip_x += (target - self.grip_x) * _ease(GRIP_FOLLOW, dt)
        self.queue_draw()
        settling = (self.press > 0 or self.held or self.current is not None
                    or (self.grip_x is not None and self.grip_target is not None
                        and abs(self.grip_target - self.grip_x) > 0.5))
        fading = any(s.ended_at is not None for s in self.strokes) and self.ctl.config["fade_seconds"] > 0
        if settling or fading:
            return GLib.SOURCE_CONTINUE
        self._tick_id = 0
        return GLib.SOURCE_REMOVE

    def _grip_target(self, cx):
        w = self.get_width()
        return min(max(cx + GRIP_LEAN * w, w * 0.15), w * 1.05)

    # ---- pointer & ink

    def move(self, x, y):
        self.cursor = (x, y)
        if self.current is not None:
            self.drag_to(x, y)
        self.wake()

    def leave(self):
        self.cursor = None
        self.grip_x = None
        self.queue_draw()

    def tap(self):
        self.press = 1.0
        self.held = True
        self.wake()

    def release(self):
        self.held = False
        if self.current is not None:
            self.current.ended_at = time.monotonic()
            self.current = None
        self.wake()

    def ink_width(self):
        return max(3.0, self.get_height() * 0.0055)

    def start_stroke(self, x, y):
        color = assets.rgba(assets.ink_color(self.ctl.config["ink"], self.ctl.style))
        self.current = Stroke(x, y, color, self.ink_width())
        self.strokes.append(self.current)

    def drag_to(self, x, y):
        if self.current is not None and self.current.extend(x, y):
            self.wake()

    @property
    def drawing(self):
        return self.current is not None

    def clear_ink(self):
        self.strokes = []
        self.current = None
        self.queue_draw()

    # ---- drawing

    def do_snapshot(self, snapshot):
        self._draw_ink(snapshot)
        if self.cursor is None or self.pointer_hidden:
            return
        if self.ctl.style == LASER or self.ctl.asset is None:
            self._draw_laser(snapshot)
        else:
            self._draw_hand(snapshot)

    def _draw_ink(self, snapshot):
        if not self.strokes:
            return
        now = time.monotonic()
        fade = self.ctl.config["fade_seconds"]
        self.strokes = [s for s in self.strokes if s.opacity(now, fade) > 0]
        shadow = assets.rgba(0x000000, 0.18)
        for s in self.strokes:
            a = s.opacity(now, fade)
            if a < 1:
                snapshot.push_opacity(a)
            stroke = Gsk.Stroke.new(s.width)
            stroke.set_line_cap(Gsk.LineCap.ROUND)
            stroke.set_line_join(Gsk.LineJoin.ROUND)
            path = s.build()
            snapshot.save()
            snapshot.translate(_point(1, 1.5))
            snapshot.append_stroke(path, stroke, shadow)
            snapshot.restore()
            snapshot.append_stroke(path, stroke, s.color)
            if a < 1:
                snapshot.pop()

    def _draw_laser(self, snapshot):
        cx, cy = self.cursor
        h = self.get_height()
        size = self.ctl.config["pointer_size"]
        r = max(4.0, h * 0.0038 * size / 0.13) * (1 + 0.2 * self.press)
        red = assets.rgba(assets.RED)

        def circle(radius):
            b = Gsk.PathBuilder.new()
            b.add_circle(_point(cx, cy), radius)
            return b.to_path()

        snapshot.push_blur(r * (2.2 + self.press))
        snapshot.append_fill(circle(r * 1.15), Gsk.FillRule.WINDING, red)
        snapshot.pop()
        snapshot.append_fill(circle(r), Gsk.FillRule.WINDING, red)
        core = Gdk.RGBA()
        core.red, core.green, core.blue, core.alpha = 1, 0.86, 0.82, 0.95
        snapshot.append_fill(circle(r * 0.45), Gsk.FillRule.WINDING, core)

    def _draw_hand(self, snapshot):
        a = self.ctl.asset
        w, h = self.get_width(), self.get_height()
        cx, cy = self.cursor
        gx = self.grip_x if self.grip_x is not None else self._grip_target(cx)
        gy = h + GRIP_DEPTH * h

        hand_pts = self.ctl.config["pointer_size"] * h * (1 - 0.06 * self.press)
        full_h = hand_pts / (a.wrist - a.hand_top)       # whole image height, in px
        width = full_h * a.aspect
        tip_len = (a.wrist - a.tip) * full_h
        tip_off_x = (a.tip_x - a.rod_x) * width

        dx, dy = cx - gx, cy - gy
        reach = math.hypot(dx, dy)
        along = math.sqrt(max(0.0, reach * reach - tip_off_x * tip_off_x))
        rod_len = max(MIN_ROD * h, along - tip_len)
        tip_angle = math.atan2(-(rod_len + tip_len), tip_off_x)
        rotation = math.degrees(math.atan2(dy, dx) - tip_angle)

        left = -a.rod_x * width

        def arm():
            # stick: image rows wrist..rod_end stretched to rod_len, ending at the grip
            span = max(1e-3, a.rod_end - a.wrist)
            rod_full = rod_len / span
            snapshot.push_clip(_rect(left, -rod_len - 1, width, rod_len + 1))
            snapshot.append_scaled_texture(a.texture, Gsk.ScalingFilter.TRILINEAR,
                                           _rect(left, -rod_len - a.wrist * rod_full, width, rod_full))
            snapshot.pop()
            # hand: image rows hand_top..wrist, sitting on top of the stick
            top = -rod_len - hand_pts
            snapshot.push_clip(_rect(left, top, width, hand_pts))
            snapshot.append_scaled_texture(a.texture, Gsk.ScalingFilter.TRILINEAR,
                                           _rect(left, top - a.hand_top * full_h, width, full_h))
            snapshot.pop()

        if self.ctl.config["shadow"]:
            # The effects must wrap the transform: GTK's GPU renderers drop a blur nested inside a rotation.
            lift = LIFT * h * (1 - 0.8 * self.press)
            snapshot.push_opacity(0.26 + 0.02 * self.press)
            snapshot.push_blur(max(1.0, lift * 0.35) + 5 * self.press)
            snapshot.push_color_matrix(_shadow_matrix(), Graphene.Vec4().init(0, 0, 0, 0))
            snapshot.save()
            snapshot.translate(_point(gx + lift * 0.6, gy + lift))
            snapshot.rotate(rotation)
            arm()
            snapshot.restore()
            snapshot.pop()
            snapshot.pop()
            snapshot.pop()

        snapshot.save()
        snapshot.translate(_point(gx, gy))
        snapshot.rotate(rotation)
        arm()
        snapshot.restore()


class Toolbar(Gtk.Box):
    """Pinned pointers, ink colour, sound, settings and exit, at the bottom of the screen."""

    def __init__(self, ctl):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.ctl = ctl
        self.set_halign(Gtk.Align.CENTER)
        self.set_valign(Gtk.Align.END)
        self.set_margin_bottom(14)

        self.hint = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.CROSSFADE)
        self.hint_label = Gtk.Label()
        self.hint_label.add_css_class("th-hint")
        self.hint.set_child(self.hint_label)
        self.hint.set_halign(Gtk.Align.CENTER)
        self.append(self.hint)

        self.revealer = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_UP,
                                     transition_duration=160)
        self.bar = Gtk.Box(spacing=4)
        self.bar.add_css_class("th-toolbar")
        self.revealer.set_child(self.bar)
        self.append(self.revealer)
        self.style_buttons = {}
        self.rebuild()

    def rebuild(self):
        while (child := self.bar.get_first_child()) is not None:
            self.bar.remove(child)
        self.style_buttons = {}
        for style in self.ctl.config["pinned"]:
            b = Gtk.Button(tooltip_text=assets.style_title(style))
            b.add_css_class("th-tool")
            if style == LASER:
                dot = Gtk.Box(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
                dot.add_css_class("th-laser-dot")
                b.set_child(dot)
            else:
                pic = Gtk.Image(pixel_size=34)
                tex = assets.thumbnail(style)
                if tex is not None:
                    pic.set_from_paintable(tex)
                b.set_child(pic)
            b.connect("clicked", lambda _b, s=style: self.ctl.pick(s))
            self.bar.append(b)
            self.style_buttons[style] = b

        self.bar.append(self._separator())

        self.ink_button = Gtk.MenuButton(tooltip_text="Ink colour")
        self.ink_button.add_css_class("th-tool")
        self.ink_swatch = Gtk.Box(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        self.ink_swatch.add_css_class("th-swatch")
        self.ink_button.set_child(self.ink_swatch)
        pop = Gtk.Popover(has_arrow=False, position=Gtk.PositionType.TOP)
        pop.add_css_class("th-popover")
        grid = Gtk.Box(spacing=4)
        for key, title, _ in assets.INK_CHOICES:
            sb = Gtk.Button(tooltip_text=title)
            sb.add_css_class("th-tool")
            sw = Gtk.Box(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
            sw.add_css_class("th-swatch")
            sw.add_css_class(f"ink-{key}")
            sb.set_child(sw)
            sb.connect("clicked", lambda _b, k=key: (self.ctl.config.set("ink", k), pop.popdown()))
            grid.append(sb)
        pop.set_child(grid)
        self.ink_button.set_popover(pop)
        self.bar.append(self.ink_button)

        self.sound_button = Gtk.Button()
        self.sound_button.add_css_class("th-tool")
        self.sound_button.connect("clicked", lambda _b: self.ctl.toggle_sound())
        self.bar.append(self.sound_button)

        settings = Gtk.Button(icon_name="emblem-system-symbolic", tooltip_text="Settings")
        settings.add_css_class("th-tool")
        settings.connect("clicked", lambda _b: self.ctl.open_settings())
        self.bar.append(settings)

        close = Gtk.Button(icon_name="window-close-symbolic", tooltip_text="Exit (Esc)")
        close.add_css_class("th-tool")
        close.connect("clicked", lambda _b: self.ctl.exit())
        self.bar.append(close)
        self.sync()

    def _separator(self):
        s = Gtk.Box()
        s.add_css_class("th-sep")
        return s

    def sync(self):
        for style, b in self.style_buttons.items():
            if style == self.ctl.style:
                b.add_css_class("selected")
            else:
                b.remove_css_class("selected")
        for key, *_ in assets.INK_CHOICES:
            self.ink_swatch.remove_css_class(f"ink-{key}")
        self.ink_swatch.add_css_class(f"ink-{self.ctl.config['ink']}")
        on = self.ctl.sound_on
        self.sound_button.set_icon_name("audio-volume-high-symbolic" if on else "audio-volume-muted-symbolic")
        self.sound_button.set_tooltip_text("Mute tap sound" if on else "Unmute tap sound")

    def show_hint(self, parts):
        markup = "    ".join(f"<b>{GLib.markup_escape_text(k)}</b> {GLib.markup_escape_text(t)}" for k, t in parts)
        self.hint_label.set_markup(markup)
        self.hint.set_reveal_child(True)

    def hide_hint(self):
        self.hint.set_reveal_child(False)


class OverlayWindow(Gtk.Window):
    def __init__(self, ctl, monitor):
        super().__init__(application=ctl.app)
        self.ctl = ctl
        self.monitor = monitor
        self.add_css_class("th-overlay")
        self.set_decorated(False)

        LayerShell.init_for_window(self)
        LayerShell.set_namespace(self, "tinyhand")
        LayerShell.set_layer(self, LayerShell.Layer.OVERLAY)
        for edge in (LayerShell.Edge.TOP, LayerShell.Edge.BOTTOM, LayerShell.Edge.LEFT, LayerShell.Edge.RIGHT):
            LayerShell.set_anchor(self, edge, True)
        LayerShell.set_exclusive_zone(self, -1)
        LayerShell.set_monitor(self, monitor)
        LayerShell.set_keyboard_mode(self, LayerShell.KeyboardMode.NONE)

        self.canvas = Canvas(ctl)
        self.toolbar = Toolbar(ctl)
        overlay = Gtk.Overlay()
        overlay.set_child(self.canvas)
        overlay.add_overlay(self.toolbar)
        self.set_child(overlay)
        self.set_cursor(Gdk.Cursor.new_from_name("none", None))

        motion = Gtk.EventControllerMotion(propagation_phase=Gtk.PropagationPhase.CAPTURE)
        motion.connect("enter", self._on_motion)
        motion.connect("motion", self._on_motion)
        motion.connect("leave", self._on_leave)
        self.add_controller(motion)

        drag = Gtk.GestureDrag(button=0)
        drag.connect("drag-begin", self._on_drag_begin)
        drag.connect("drag-update", self._on_drag_update)
        drag.connect("drag-end", self._on_drag_end)
        self.canvas.add_controller(drag)
        self._down = None

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key_pressed)
        keys.connect("key-released", self._on_key_released)
        self.add_controller(keys)

        self._passthrough = False

    # ---- keyboard focus follows the pointer between monitors

    def set_keyboard(self, exclusive):
        LayerShell.set_keyboard_mode(
            self, LayerShell.KeyboardMode.EXCLUSIVE if exclusive else LayerShell.KeyboardMode.NONE)

    # ---- pointer

    def _on_motion(self, _c, x, y):
        self.ctl.pointer_entered(self)
        self.canvas.move(x, y)
        self.update_toolbar_reveal()

    def _on_leave(self, _c):
        self.canvas.leave()

    def _on_drag_begin(self, gesture, x, y):
        self._down = (x, y)
        self.canvas.cursor = (x, y)
        self.canvas.tap()
        self.ctl.tapped()
        self.toolbar.hide_hint()

    def _on_drag_update(self, gesture, ox, oy):
        if self._down is None:
            return
        x, y = self._down[0] + ox, self._down[1] + oy
        if gesture.get_current_button() == 1 and not self.canvas.drawing \
                and math.hypot(ox, oy) >= DRAG_START:
            self.canvas.start_stroke(*self._down)
            self.update_toolbar_reveal()
        self.canvas.move(x, y)

    def _on_drag_end(self, _g, _ox, _oy):
        self._down = None
        self.canvas.release()
        self.update_toolbar_reveal()

    def update_toolbar_reveal(self):
        c = self.canvas.cursor
        w, h = self.get_width(), self.get_height()
        near = False
        if c is not None:
            bar_w = self.toolbar.bar.measure(Gtk.Orientation.HORIZONTAL, -1)[1]
            near = c[1] > h - 120 and abs(c[0] - w / 2) < bar_w / 2 + 80
        show = not self.canvas.drawing and (near or time.monotonic() < self.ctl.reveal_until)
        if self.toolbar.revealer.get_reveal_child() != show:
            self.toolbar.revealer.set_reveal_child(show)

    # ---- keys

    def _on_key_pressed(self, _c, keyval, _code, state):
        mods = state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.ALT_MASK
                        | Gdk.ModifierType.SHIFT_MASK | Gdk.ModifierType.SUPER_MASK)
        ctrl_alt = Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.ALT_MASK
        lower = Gdk.keyval_to_lower(keyval)
        if keyval == Gdk.KEY_Escape:
            self.ctl.exit()
            return True
        if mods == ctrl_alt and lower == Gdk.KEY_x:
            self.ctl.clear()
            return True
        if mods == ctrl_alt and lower == Gdk.KEY_h:
            self.ctl.deactivate()
            return True
        key = INTERACT_KEYS.get(self.ctl.config["interact_key"])
        if key and keyval in key[0]:
            self.ctl.set_passthrough(True)
        return False

    def _on_key_released(self, _c, keyval, _code, _state):
        key = INTERACT_KEYS.get(self.ctl.config["interact_key"])
        if key and keyval in key[0]:
            self.ctl.set_passthrough(False)

    # ---- "hold Alt to click for real": let clicks fall through to the windows below

    def set_passthrough(self, on):
        if on == self._passthrough:
            return
        surface = self.get_surface()
        if surface is None:
            return
        self._passthrough = on
        if on:
            surface.set_input_region(cairo.Region())
            self.canvas.pointer_hidden = True
            self.canvas.release()
            self._down = None
        else:
            surface.set_input_region(cairo.Region(cairo.RectangleInt(0, 0, 1 << 15, 1 << 15)))
            self.canvas.pointer_hidden = False
        self.canvas.queue_draw()
