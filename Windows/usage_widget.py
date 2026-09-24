"""Codex & Claude usage tracker for Windows; Qt display with Tk settings."""
import argparse
import datetime as dt
from decimal import Decimal, InvalidOperation
import json
import os
import platform
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import tempfile

ROOT = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex')))
CONFIG_FILE = (Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'Codex Usage Tracker' / 'config.json'
               if getattr(sys, 'frozen', False) else Path(__file__).parent / 'config.json')


def load_config():
    """Load configuration from config.json."""
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE) as f:
                value = json.load(f)
                return value if isinstance(value, dict) else {}
        except (json.JSONDecodeError, IOError):
            return {}
    return {}


def save_config(config):
    """Save configuration to config.json."""
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=CONFIG_FILE.parent, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(config, stream, indent=2)
        os.replace(temporary, CONFIG_FILE)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def allowance_window(result, duration_minutes):
    buckets = result.get('rateLimitsByLimitId') or {}
    bucket = buckets.get('codex') or result.get('rateLimits') or result
    for name in ('primary', 'secondary'):
        window = bucket.get(name) or {}
        minutes = window.get('windowDurationMins', window.get('window_minutes'))
        if minutes == duration_minutes:
            used = window.get('usedPercent', window.get('used_percent'))
            reset = window.get('resetsAt', window.get('resets_at'))
            if used is not None and reset is not None:
                return max(0, min(100, 100 - float(used))), int(reset)
    return None


def five_hour(result):
    value = allowance_window(result, 300)
    if value is None:
        raise ValueError('Five-hour allowance unavailable for this account')
    return value


def credit_balance(result):
    """Return the service's purchased-credit balance, never an estimate."""
    buckets = result.get('rateLimitsByLimitId') or {}
    bucket = buckets.get('codex') or result.get('rateLimits') or result
    credits = bucket.get('credits') or {}
    if credits.get('unlimited') is True:
        return 'Unlimited'
    balance = credits.get('balance')
    if balance is None or isinstance(balance, bool):
        return None
    try:
        value = Decimal(str(balance))
    except InvalidOperation:
        return None
    return value if value.is_finite() and value >= 0 else None


def find_codex():
    import shutil
    found = shutil.which('codex.exe' if os.name == 'nt' else 'codex')
    if found:
        return found
    machine = platform.machine().lower()
    arch = 'aarch64' if machine in ('aarch64', 'arm64') else 'x86_64'
    binary = f'windows-{arch}/codex.exe' if os.name == 'nt' else f'linux-{arch}/codex'
    candidates = []
    for directory in ('.vscode/extensions', '.vscode-insiders/extensions', '.vscode-server/extensions'):
        candidates.extend((Path.home() / directory).glob(f'openai.chatgpt-*/bin/{binary}'))
    candidates = [p for p in candidates if p.is_file() and os.access(p, os.X_OK)]
    if candidates:
        return str(max(candidates, key=lambda p: p.stat().st_mtime))
    raise RuntimeError('Codex executable not found')


class Connection:
    def __init__(self):
        self.process = None
        self.sequence = 0
        self.messages = queue.Queue()

    def send(self, data):
        self.process.stdin.write(json.dumps(data) + '\n')
        self.process.stdin.flush()

    def request(self, method, params=None):
        self.sequence += 1
        request_id = self.sequence
        self.send({'id': request_id, 'method': method, 'params': params or {}})
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            try:
                message = self.messages.get(timeout=0.25)
            except queue.Empty:
                if self.process.poll() is not None:
                    raise RuntimeError('Codex usage service exited')
                continue
            if message.get('id') == request_id:
                if 'error' in message:
                    raise RuntimeError(message['error'].get('message', 'Usage request failed'))
                return message.get('result', {})
        raise TimeoutError('Usage refresh timed out')

    def start(self):
        self.process = subprocess.Popen([find_codex(), 'app-server'], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding='utf-8',
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        stream = self.process.stdout
        def read():
            for line in stream:
                try:
                    self.messages.put(json.loads(line))
                except ValueError:
                    pass
        threading.Thread(target=read, daemon=True).start()
        self.request('initialize', {'clientInfo': {'name': 'local_usage_widget', 'version': '1.0.0'}})
        self.send({'method': 'initialized', 'params': {}})

    def refresh(self):
        if self.process is None or self.process.poll() is not None:
            self.start()
        return five_hour(self.request('account/rateLimits/read'))

    def refresh_snapshot(self):
        if self.process is None or self.process.poll() is not None:
            self.start()
        result = self.request('account/rateLimits/read')
        try:
            quota = five_hour(result)
        except ValueError:
            quota = None
        return quota, credit_balance(result), allowance_window(result, 10080)

    def close(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()


class SessionWatcher:
    """Tail new local events; never modify or retain conversation contents."""
    def __init__(self):
        self.offsets = {}
        self.paths = []
        self.last_scan = 0

    def poll(self):
        now = time.monotonic()
        if now - self.last_scan > 10:
            self.last_scan = now
            paths = ROOT.joinpath('sessions').glob('**/*.jsonl')
            self.paths = [p for p in paths if time.time() - p.stat().st_mtime < 86400]
        completed = False
        latest = None
        for path in self.paths:
            try:
                size = path.stat().st_size
                if path not in self.offsets:
                    self.offsets[path] = size
                    continue
                offset = self.offsets[path]
                if size < offset:
                    offset = 0
                if size == offset:
                    continue
                with path.open('rb') as stream:
                    stream.seek(offset)
                    for line in stream:
                        if not line.endswith(b'\n'):
                            break
                        offset += len(line)
                        try:
                            event = json.loads(line)
                            payload = event.get('payload', {})
                            if event.get('type') == 'event_msg':
                                if payload.get('type') in ('task_complete', 'turn_complete'):
                                    completed = True
                                if payload.get('type') == 'token_count' and payload.get('rate_limits'):
                                    stamp = event.get('timestamp', '')
                                    value = five_hour(payload['rate_limits'])
                                    if latest is None or stamp > latest[0]:
                                        latest = (stamp, value)
                        except (ValueError, TypeError):
                            pass
                self.offsets[path] = offset
            except OSError:
                continue
        return completed, latest


def run_settings_dialog(parent):
    import compact_ui
    import sys
    return compact_ui.settings(parent, sys.modules[__name__])


def run_widget():
    import compact_ui
    import sys
    compact_ui.run(sys.modules[__name__])


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true', help='Read live quota without opening a window')
    args = parser.parse_args()
    if args.check:
        client = Connection()
        try:
            remaining, reset = client.refresh()
            print(json.dumps({'remaining_percent': remaining, 'resets_at': dt.datetime.fromtimestamp(reset).isoformat()}))
        finally:
            client.close()
    else:
        run_widget()
