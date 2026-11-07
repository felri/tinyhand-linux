"""Tray icon (StatusNotifierItem + com.canonical.dbusmenu), the Linux stand-in for the menu bar icon.

Left click toggles the pointer, right click opens a small menu.
"""

import os

from gi.repository import Gio, GLib

from .assets import ICONS_DIR

SNI_XML = """
<node>
  <interface name="org.kde.StatusNotifierItem">
    <property name="Category" type="s" access="read"/>
    <property name="Id" type="s" access="read"/>
    <property name="Title" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="IconName" type="s" access="read"/>
    <property name="IconPixmap" type="a(iiay)" access="read"/>
    <property name="ToolTip" type="(sa(iiay)ss)" access="read"/>
    <property name="ItemIsMenu" type="b" access="read"/>
    <property name="Menu" type="o" access="read"/>
    <method name="Activate"><arg name="x" type="i" direction="in"/><arg name="y" type="i" direction="in"/></method>
    <method name="SecondaryActivate"><arg name="x" type="i" direction="in"/><arg name="y" type="i" direction="in"/></method>
    <method name="ContextMenu"><arg name="x" type="i" direction="in"/><arg name="y" type="i" direction="in"/></method>
    <method name="Scroll"><arg name="delta" type="i" direction="in"/><arg name="orientation" type="s" direction="in"/></method>
    <signal name="NewIcon"/>
    <signal name="NewToolTip"/>
    <signal name="NewStatus"><arg name="status" type="s"/></signal>
  </interface>
</node>"""

MENU_XML = """
<node>
  <interface name="com.canonical.dbusmenu">
    <property name="Version" type="u" access="read"/>
    <property name="TextDirection" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="IconThemePath" type="as" access="read"/>
    <method name="GetLayout">
      <arg type="i" name="parentId" direction="in"/>
      <arg type="i" name="recursionDepth" direction="in"/>
      <arg type="as" name="propertyNames" direction="in"/>
      <arg type="u" name="revision" direction="out"/>
      <arg type="(ia{sv}av)" name="layout" direction="out"/>
    </method>
    <method name="GetGroupProperties">
      <arg type="ai" name="ids" direction="in"/>
      <arg type="as" name="propertyNames" direction="in"/>
      <arg type="a(ia{sv})" name="properties" direction="out"/>
    </method>
    <method name="GetProperty">
      <arg type="i" name="id" direction="in"/>
      <arg type="s" name="name" direction="in"/>
      <arg type="v" name="value" direction="out"/>
    </method>
    <method name="Event">
      <arg type="i" name="id" direction="in"/>
      <arg type="s" name="eventId" direction="in"/>
      <arg type="v" name="data" direction="in"/>
      <arg type="u" name="timestamp" direction="in"/>
    </method>
    <method name="EventGroup">
      <arg type="a(isvu)" name="events" direction="in"/>
      <arg type="ai" name="idErrors" direction="out"/>
    </method>
    <method name="AboutToShow">
      <arg type="i" name="id" direction="in"/>
      <arg type="b" name="needUpdate" direction="out"/>
    </method>
    <method name="AboutToShowGroup">
      <arg type="ai" name="ids" direction="in"/>
      <arg type="ai" name="updatesNeeded" direction="out"/>
      <arg type="ai" name="idErrors" direction="out"/>
    </method>
    <signal name="ItemsPropertiesUpdated">
      <arg type="a(ia{sv})" name="updatedProps"/>
      <arg type="a(ias)" name="removedProps"/>
    </signal>
    <signal name="LayoutUpdated">
      <arg type="u" name="revision"/>
      <arg type="i" name="parent"/>
    </signal>
  </interface>
</node>"""

ITEM_PATH = "/StatusNotifierItem"
MENU_PATH = "/MenuBar"
WATCHER = "org.kde.StatusNotifierWatcher"


def _pixmaps(filename):
    """White glyph from the template PNG, as SNI ARGB32 pixmaps."""
    try:
        from PIL import Image

        with Image.open(ICONS_DIR / filename) as im:
            im = im.convert("RGBA")
            out = []
            for size in (22, 44):
                small = im.resize((size, size), Image.LANCZOS)
                data = bytearray()
                for _r, _g, _b, a in small.getdata():
                    data += bytes((a, 255, 255, 255))
                out.append((size, size, bytes(data)))
            return out
    except Exception as e:
        print(f"tinyhand: tray icon: {e}")
        return []


class Tray:
    def __init__(self, ctl):
        self.ctl = ctl
        self.revision = 1
        self.bus = None
        self.name = f"org.kde.StatusNotifierItem-{os.getpid()}-1"
        self.icons = {True: _pixmaps("menubar_on@2x.png"), False: _pixmaps("menubar_off@2x.png")}
        Gio.bus_get(Gio.BusType.SESSION, None, self._on_bus)

    def _on_bus(self, _src, res):
        try:
            self.bus = Gio.bus_get_finish(res)
        except GLib.Error as e:
            print(f"tinyhand: no session bus for the tray icon: {e.message}")
            return
        sni = Gio.DBusNodeInfo.new_for_xml(SNI_XML).interfaces[0]
        menu = Gio.DBusNodeInfo.new_for_xml(MENU_XML).interfaces[0]
        self.bus.register_object(ITEM_PATH, sni, self._sni_call, self._sni_prop, None)
        self.bus.register_object(MENU_PATH, menu, self._menu_call, self._menu_prop, None)
        Gio.bus_own_name_on_connection(self.bus, self.name, Gio.BusNameOwnerFlags.NONE, None, None)
        Gio.bus_watch_name_on_connection(self.bus, WATCHER, Gio.BusNameWatcherFlags.NONE,
                                         self._register, None)

    def _register(self, *_):
        self.bus.call(WATCHER, "/StatusNotifierWatcher", WATCHER, "RegisterStatusNotifierItem",
                      GLib.Variant("(s)", (self.name,)), None, Gio.DBusCallFlags.NONE, -1, None, None)

    def update(self):
        """Pointer turned on or off: refresh icon, tooltip and the menu label."""
        if self.bus is None:
            return
        for sig in ("NewIcon", "NewToolTip"):
            self.bus.emit_signal(None, ITEM_PATH, "org.kde.StatusNotifierItem", sig, None)
        self.revision += 1
        self.bus.emit_signal(None, MENU_PATH, "com.canonical.dbusmenu", "LayoutUpdated",
                             GLib.Variant("(ui)", (self.revision, 0)))

    # ---- StatusNotifierItem

    def _sni_prop(self, _conn, _sender, _path, _iface, prop):
        active = self.ctl.active
        state = "on" if active else "off"
        values = {
            "Category": GLib.Variant("s", "ApplicationStatus"),
            "Id": GLib.Variant("s", "tinyhand"),
            "Title": GLib.Variant("s", "TinyHand"),
            "Status": GLib.Variant("s", "Active"),
            "IconName": GLib.Variant("s", ""),
            "IconPixmap": GLib.Variant("a(iiay)", self.icons[active]),
            "ToolTip": GLib.Variant("(sa(iiay)ss)", ("", [], "TinyHand", f"Pointer is {state}. Click to toggle.")),
            "ItemIsMenu": GLib.Variant("b", False),
            "Menu": GLib.Variant("o", MENU_PATH),
        }
        return values.get(prop)

    def _sni_call(self, _conn, _sender, _path, _iface, method, _params, invocation):
        if method == "Activate":
            GLib.idle_add(lambda: self.ctl.toggle() and False)
        elif method in ("SecondaryActivate", "ContextMenu"):
            GLib.idle_add(lambda: self.ctl.open_settings() and False)
        invocation.return_value(None)

    # ---- dbusmenu

    def _items(self):
        def item(i, label, **extra):
            props = {"label": GLib.Variant("s", label), "enabled": GLib.Variant("b", True),
                     "visible": GLib.Variant("b", True)}
            props.update(extra)
            return i, props

        return [
            item(1, "Turn pointer off" if self.ctl.active else "Turn pointer on"),
            item(2, "Clear drawing"),
            (3, {"type": GLib.Variant("s", "separator"), "visible": GLib.Variant("b", True)}),
            item(4, "Settings…"),
            item(5, "Quit TinyHand"),
        ]

    def _layout(self):
        children = [GLib.Variant("(ia{sv}av)", (i, props, [])) for i, props in self._items()]
        root = (0, {"children-display": GLib.Variant("s", "submenu")}, children)
        return GLib.Variant("(u(ia{sv}av))", (self.revision, root))

    def _menu_prop(self, _conn, _sender, _path, _iface, prop):
        return {
            "Version": GLib.Variant("u", 3),
            "TextDirection": GLib.Variant("s", "ltr"),
            "Status": GLib.Variant("s", "normal"),
            "IconThemePath": GLib.Variant("as", []),
        }.get(prop)

    def _menu_call(self, _conn, _sender, _path, _iface, method, params, invocation):
        if method == "GetLayout":
            invocation.return_value(self._layout())
        elif method == "GetGroupProperties":
            ids = params.unpack()[0]
            items = [(i, p) for i, p in self._items() if not ids or i in ids]
            invocation.return_value(GLib.Variant("(a(ia{sv}))", (items,)))
        elif method == "GetProperty":
            i, name = params.unpack()
            props = dict(self._items()).get(i, {})
            invocation.return_value(GLib.Variant("(v)", (props.get(name, GLib.Variant("s", "")),)))
        elif method == "Event":
            i, event, _data, _ts = params.unpack()
            if event == "clicked":
                GLib.idle_add(self._clicked, i)
            invocation.return_value(None)
        elif method == "EventGroup":
            for i, event, _data, _ts in params.unpack()[0]:
                if event == "clicked":
                    GLib.idle_add(self._clicked, i)
            invocation.return_value(GLib.Variant("(ai)", ([],)))
        elif method == "AboutToShow":
            invocation.return_value(GLib.Variant("(b)", (False,)))
        elif method == "AboutToShowGroup":
            invocation.return_value(GLib.Variant("(aiai)", ([], [])))
        else:
            invocation.return_value(None)

    def _clicked(self, i):
        actions = {1: self.ctl.toggle, 2: self.ctl.clear, 4: self.ctl.open_settings, 5: self.ctl.quit}
        if i in actions:
            actions[i]()
        return False
