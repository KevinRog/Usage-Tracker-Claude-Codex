"""Formatting helpers and the tracker entry point."""
import time

CODEX_REFRESH_SECONDS = 15
CLAUDE_REFRESH_SECONDS = 60


def format_usage(value):
    if not value:
        return '-- --'
    remaining, reset = value
    if reset <= time.time():
        return 'Reset due --'
    minutes = int((reset-time.time()+59)//60)
    return f'{minutes//60}h {minutes%60:02d}m  {remaining:g}%'


def format_credits(value, stale=False):
    if value is None:
        return 'Unavailable'
    text = value if isinstance(value, str) else f'{value:,.4f}'
    return text + (' *' if stale else '')


def settings(parent, backend):
    from settings_ui import open_settings
    return open_settings(parent, backend)


def run(backend):
    from qt_tracker import run as run_tracker
    run_tracker(backend)
