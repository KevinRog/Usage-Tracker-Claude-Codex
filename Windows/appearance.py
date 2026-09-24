"""Persisted, validated theme roles with live widget updates."""
import re
import math
import tkinter as tk

COLORS = {
    'background': ('Background', '#151b27'),
    'panel': ('Settings cards', '#1d2737'),
    'text': ('Labels and text', '#e2e8f0'),
    'muted': ('Headings and hints', '#8191a9'),
    'codex': ('Codex allowance', '#71e4b0'),
    'credits': ('Codex credits', '#71e4b0'),
    'claude': ('Claude allowance', '#71e4b0'),
    'warning': ('Warnings / unavailable', '#ffb56b'),
    'border': ('Outer border', '#34445c'),
    'divider': ('Dividers', '#2c394d'),
    'button': ('Buttons', '#263449'),
    'button_text': ('Button icons / text', '#a8b6cc'),
    'hover': ('Button hover', '#30435e'),
    'hover_text': ('Hover text', '#ffffff'),
    'close_hover': ('Close button hover', '#a83848'),
}


def normalize(data):
    data = data if isinstance(data, dict) else {}
    colors = data.get('colors') if isinstance(data.get('colors'), dict) else {}
    result = {'colors': {key: value if isinstance(value := colors.get(key), str) and
                        re.fullmatch(r'#[0-9a-fA-F]{6}', value) else default
                        for key, (_, default) in COLORS.items()}}
    try:
        opacity = float(data.get('opacity', 1))
        result['opacity'] = max(0.4, min(1.0, opacity)) if math.isfinite(opacity) else 1.0
    except (TypeError, ValueError):
        result['opacity'] = 1.0
    # Migrate the old color-key mode: Windows treats its clear pixels as
    # holes for mouse input. Uniform nonzero alpha keeps the whole GUI usable.
    if data.get('transparent_background') is True:
        result['opacity'] = min(result['opacity'], 0.8)
    providers = data.get('providers', ['codex', 'claude'])
    result['providers'] = [name for name in ('codex', 'claude')
                           if isinstance(providers, list) and name in providers] or ['codex', 'claude']
    return result


class Theme:
    def __init__(self, root, data=None, renderer=None):
        self.root = root
        self.data = normalize(data)
        self.widgets = {}
        self.renderer = renderer

    def color(self, role):
        return self.data['colors'][role]

    def bind(self, widget, **roles):
        self.widgets.setdefault(widget, {}).update(roles)
        widget.configure(**{option: self.color(role) for option, role in roles.items()})
        return widget

    def bind_tree(self, widget):
        # Capture roles once so choosing identical colors never merges roles.
        defaults = {color: key for key, (_, color) in COLORS.items() if key not in ('credits', 'claude')}
        defaults['white'] = 'hover_text'
        roles = {}
        for option in ('background', 'foreground', 'activebackground', 'activeforeground',
                       'highlightbackground', 'highlightcolor', 'troughcolor', 'selectcolor',
                       'insertbackground', 'disabledforeground'):
            try:
                role = defaults.get(str(widget.cget(option)))
                if role:
                    roles[option] = role
            except tk.TclError:
                pass
        if roles:
            self.bind(widget, **roles)
        for child in widget.winfo_children():
            self.bind_tree(child)

    def apply(self, data):
        self.data = normalize(data)
        for widget, roles in list(self.widgets.items()):
            try:
                if not widget.winfo_exists():
                    del self.widgets[widget]
                    continue
                widget.configure(**{option: self.color(role) for option, role in roles.items()})
            except tk.TclError:
                self.widgets.pop(widget, None)
        if self.root.tk.call('tk', 'windowingsystem') == 'win32':
            self.root.attributes('-transparentcolor', '')
        # Settings and text never inherit the background's alpha.
        self.root.attributes('-alpha', 1.0)
        if self.renderer is not None:
            self.renderer(self.data)
