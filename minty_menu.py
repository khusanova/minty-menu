#!/usr/bin/env python3
"""
Minty Menu — A minimal, distraction-free app grid for Linux Mint.

Usage:
  1. Edit the apps.list file — just drop names of the applications you want
  to add to the menu or full paths to desktop files.
  Files are looked up in /usr/share/applications/ and
  ~/.local/share/applications/ automatically.
  2. Run:  python3 mini-launcher.py
  3. (Optional) Bind to a keyboard shortcut for instant access.

The launcher reads Name, Icon, and Exec from each .desktop file so you
don't have to figure out commands or icon names yourself.
"""

import configparser
import os
import re
import subprocess
import sys
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GdkPixbuf, Pango


PATH_TO_APPS_LIST = "apps.list"


def load_apps_list() -> list[str]:
    """Load names of applications from the apps list file.

    Reads PATH_TO_APPS_LIST line by line, strips whitespace, and returns
    the entries.

    Returns:
        List of stripped application names, or an empty list
        if the file could not be read.
    """
    try:
        with open(PATH_TO_APPS_LIST, "r", encoding="utf-8") as f:
            apps_list = [line.strip() for line in f.readlines() if not
                         line.startswith("#")]
            return apps_list
    except FileNotFoundError:
        print(f"App list not found: {PATH_TO_APPS_LIST} does not exist.",
              file=sys.stderr)
    except PermissionError:
        print(f"Cannot read file {PATH_TO_APPS_LIST}. Permission denied.",
              file=sys.stderr)
    except UnicodeDecodeError:
        print(f"Cannot read file {PATH_TO_APPS_LIST}. Encoding should be "
              "UTF-8.", file=sys.stderr)
    except OSError as e:
        print(f"Failed to load {PATH_TO_APPS_LIST}: {e}",
              file=sys.stderr)
    return []


DESKTOP_FILES = load_apps_list()

# Standard directories where .desktop files live
DESKTOP_DIRS = [
    os.path.expanduser("~/.local/share/applications"),
    "/usr/share/applications",
    "/usr/local/share/applications",
    "/var/lib/flatpak/exports/share/applications",
    os.path.expanduser("~/.local/share/flatpak/exports/share/applications"),
    "/var/lib/snapd/desktop/applications",
]

TERMINAL_EMULATOR = "x-terminal-emulator"


def _resolve_appname(entry):
    """Resolve a .desktop filename or path to an absolute path."""
    if not entry.endswith('.desktop'):
        entry += '.desktop'
    expanded = os.path.expanduser(entry)
    if os.path.isabs(expanded) and os.path.isfile(expanded):
        return expanded
    for d in DESKTOP_DIRS:
        full = os.path.join(d, entry)
        if os.path.isfile(full):
            return full
    return None


def _clean_exec(exec_str):
    """Remove field codes (%f, %F, %u, %U, etc.) from Exec lines."""
    return re.sub(r'%[a-zA-Z]', '', exec_str).strip()


def _parse_desktop_file(path):
    """Parse a .desktop file and return {name, icon, cmd} or None."""
    try:
        cp = configparser.RawConfigParser()
        cp.read(path, encoding="utf-8")
        section = "Desktop Entry"
        if not cp.has_section(section):
            return None
        name = cp.get(section, "Name", fallback=None)
        icon = cp.get(section, "Icon", fallback="application-x-executable")
        exec_raw = cp.get(section, "Exec", fallback=None)
        if not name or not exec_raw:
            return None
        cmd = _clean_exec(exec_raw)
        # Handle Terminal=true apps
        terminal = (cp.get(section, "Terminal", fallback="false").lower() ==
                    "true")
        if terminal:
            # Wrap in a terminal emulator
            cmd = f"{TERMINAL_EMULATOR} -e {cmd}"
        return {"name": name, "icon": icon, "cmd": cmd}
    except Exception as e:
        print(f"Warning: could not parse {path}: {e}", file=sys.stderr)
        return None


def load_apps():
    """Load app entries from the DESKTOP_FILES list."""
    apps = []
    for entry in DESKTOP_FILES:
        path = _resolve_appname(entry)
        if path is None:
            print(f"Warning: could not find '{entry}', skipping.",
                  file=sys.stderr)
            continue
        app = _parse_desktop_file(path)
        if app:
            apps.append(app)
        else:
            print(f"Warning: could not parse '{entry}', skipping.",
                  file=sys.stderr)
    return apps


APPS = load_apps()

# Grid layout
COLUMNS = 3          # number of columns in the grid
ICON_SIZE = 64       # icon size in pixels
WINDOW_WIDTH = 520
WINDOW_HEIGHT = -1   # auto-fit to content

# ─── COLOURS / STYLE ───────────────────────────────────────────────
CSS = b"""
window {
    background-color: #1a1b26;
    border-radius: 18px;
}
.app-button {
    background: transparent;
    border: none;
    border-radius: 14px;
    padding: 16px 8px;
    transition: background 200ms ease;
}
.app-button:hover {
    background-color: rgba(255,255,255,0.08);
}
.app-button:active {
    background-color: rgba(255,255,255,0.14);
}
.app-label {
    color: #c0caf5;
    font-size: 12px;
    font-weight: 500;
}
.search-entry {
    background-color: rgba(255,255,255,0.06);
    color: #c0caf5;
    border: 1px solid rgba(255,255,255,0.1);
    border-radius: 10px;
    padding: 8px 14px;
    font-size: 14px;
    caret-color: #7aa2f7;
}
.search-entry:focus {
    border-color: #7aa2f7;
    background-color: rgba(255,255,255,0.09);
}
.title-label {
    color: #7aa2f7;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 2px;
}
"""


class MiniLauncher(Gtk.Window):
    def __init__(self):
        super().__init__(title="Minty Menu")
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_default_size(WINDOW_WIDTH, WINDOW_HEIGHT)
        self.set_keep_above(True)
        self.set_type_hint(Gdk.WindowTypeHint.DIALOG)

        # Allow transparency
        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual:
            self.set_visual(visual)
        self.set_app_paintable(True)

        # Load CSS
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(
            screen, css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        # Close on Escape
        self.connect("key-press-event", self._on_key)
        # Close on focus loss
        self.connect("focus-out-event", lambda *a: self.close())

        # ── Layout ──
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        vbox.set_margin_top(20)
        vbox.set_margin_bottom(20)
        vbox.set_margin_start(20)
        vbox.set_margin_end(20)

        # Title
        title = Gtk.Label(label="MINTY MENU")
        title.get_style_context().add_class("title-label")
        vbox.pack_start(title, False, False, 0)

        # Search
        self.search = Gtk.Entry()
        self.search.set_placeholder_text("Search apps…")
        self.search.get_style_context().add_class("search-entry")
        self.search.connect("changed", self._on_search)
        vbox.pack_start(self.search, False, False, 4)

        # Grid
        self.grid = Gtk.FlowBox()
        self.grid.set_max_children_per_line(COLUMNS)
        self.grid.set_min_children_per_line(COLUMNS)
        self.grid.set_selection_mode(Gtk.SelectionMode.NONE)
        self.grid.set_homogeneous(True)
        self.grid.set_row_spacing(4)
        self.grid.set_column_spacing(4)

        self.buttons = []
        for app in APPS:
            btn = self._make_button(app)
            self.grid.add(btn)
            self.buttons.append((app, btn))

        vbox.pack_start(self.grid, True, True, 0)
        self.add(vbox)
        self.show_all()

    # ── Helpers ─────────────────────────────────────────────────────
    def _make_button(self, app):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_halign(Gtk.Align.CENTER)

        # Icon
        icon_widget = self._load_icon(app["icon"])
        box.pack_start(icon_widget, False, False, 0)

        # Label
        label = Gtk.Label(label=app["name"])
        label.get_style_context().add_class("app-label")
        label.set_ellipsize(Pango.EllipsizeMode.END)
        label.set_max_width_chars(12)
        box.pack_start(label, False, False, 0)

        btn = Gtk.Button()
        btn.get_style_context().add_class("app-button")
        btn.add(box)
        btn.set_relief(Gtk.ReliefStyle.NONE)
        btn.connect("clicked", lambda *a, c=app["cmd"]: self._launch(c))
        return btn

    def _load_icon(self, icon_name):
        theme = Gtk.IconTheme.get_default()
        # Try as a theme icon name first
        if theme.has_icon(icon_name):
            img = Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.DIALOG)
            img.set_pixel_size(ICON_SIZE)
            return img
        # Try as a file path
        if os.path.isfile(icon_name):
            pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(
                icon_name, ICON_SIZE, ICON_SIZE, True
            )
            return Gtk.Image.new_from_pixbuf(pixbuf)
        # Fallback
        img = Gtk.Image.new_from_icon_name("application-x-executable",
                                           Gtk.IconSize.DIALOG)
        img.set_pixel_size(ICON_SIZE)
        return img

    def _launch(self, cmd):
        subprocess.Popen(cmd, shell=True, start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.close()

    def _on_key(self, widget, event):
        if event.keyval == Gdk.KEY_Escape:
            self.close()
            return True
        return False

    def _on_search(self, entry):
        query = entry.get_text().lower().strip()
        for app, btn in self.buttons:
            parent = btn.get_parent()  # FlowBoxChild
            if parent:
                visible = query == "" or query in app["name"].lower()
                parent.set_visible(visible)


if __name__ == "__main__":
    launcher = MiniLauncher()
    launcher.connect("destroy", Gtk.main_quit)
    Gtk.main()
