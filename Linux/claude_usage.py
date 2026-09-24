"""Read subscription limits using the existing local Claude Code sign-in."""
import datetime as dt
import json
import math
import os
from pathlib import Path
import urllib.error
import urllib.request


class UsageError(Exception):
    def __init__(self, message, retry_after=60):
        super().__init__(message)
        self.retry_after = retry_after


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward the subscription credential to another destination.
        return None


def parse_window(window):
    if not isinstance(window, dict):
        return None
    used = window.get('utilization', window.get('used_percentage'))
    reset = window.get('resets_at')
    if used is None or reset is None or isinstance(used, bool) or isinstance(reset, bool):
        return None
    try:
        used = float(used)
        if isinstance(reset, str) and 'T' in reset:
            stamp = dt.datetime.fromisoformat(reset.replace('Z', '+00:00'))
            if stamp.tzinfo is None:
                return None
            reset = stamp.timestamp()
        reset = float(reset)
        if not math.isfinite(used) or not 0 <= used <= 100 or not math.isfinite(reset) or reset <= 0:
            return None
        return 100 - used, int(reset)
    except (ValueError, TypeError, OverflowError):
        return None


def fetch_usage():
    directory = Path(os.environ.get('CLAUDE_CONFIG_DIR', str(Path.home() / '.claude')))
    try:
        data = json.loads((directory / '.credentials.json').read_text(encoding='utf-8-sig'))
        auth = data.get('claudeAiOauth') or {}
        token = auth.get('accessToken')
        if not isinstance(token, str) or not token:
            raise ValueError
    except (OSError, ValueError, TypeError, AttributeError):
        raise UsageError('Sign in to Claude Code in VS Code to read subscription usage.') from None
    request = urllib.request.Request('https://api.anthropic.com/api/oauth/usage', headers={
        'Authorization': 'Bearer ' + token,
        'anthropic-beta': 'oauth-2025-04-20',
        'User-Agent': 'CodexUsageTracker/1.0',
        'Accept': 'application/json',
    })
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=15) as response:
            data = json.load(response)
        if not isinstance(data, dict):
            raise ValueError
        return {name: parse_window(data.get(name)) for name in ('five_hour', 'seven_day')}
    except urllib.error.HTTPError as exc:
        exc.close()
        if exc.code in (401, 403):
            raise UsageError('Claude sign-in expired or usage access denied. Sign in again in VS Code.') from None
        if exc.code == 429:
            try:
                delay = max(300, min(3600, int(exc.headers.get('Retry-After', '300'))))
            except (ValueError, TypeError):
                delay = 300
            raise UsageError('Claude usage service is busy. Retrying later.', delay) from None
        raise UsageError(f'Claude usage service returned HTTP {exc.code}.') from None
    except (OSError, ValueError, TypeError):
        raise UsageError('Could not read Claude usage. Check your connection and Claude sign-in.') from None
