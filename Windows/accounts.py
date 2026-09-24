"""Use installed clients for account status and browser-based sign-in."""
import json
import os
from pathlib import Path
import shutil
import subprocess


def find_claude():
    executable = 'claude.exe' if os.name == 'nt' else 'claude'
    found = shutil.which(executable)
    if found:
        return found
    native = Path.home() / '.local/bin' / executable
    if native.is_file():
        return str(native)
    candidates = []
    for directory in ('.vscode/extensions', '.vscode-insiders/extensions', '.vscode-server/extensions'):
        candidates.extend((Path.home() / directory).glob(
            f'anthropic.claude-code-*/resources/native-binary/{executable}'))
    if candidates:
        return str(max(candidates, key=lambda path: path.stat().st_mtime))
    raise FileNotFoundError('Install Claude Code or its VS Code extension to connect.')


def status(provider, backend):
    if provider == 'codex':
        client = backend.Connection()
        try:
            client.start()
            account = client.request('account/read', {'refreshToken': False}).get('account')
        finally:
            client.close()
        if not account:
            return {'signed_in': False, 'supported': False, 'text': 'Not signed in'}
        supported = account.get('type') == 'chatgpt'
        plan = account.get('planType') or 'ChatGPT'
        return {'signed_in': True, 'supported': supported,
                'text': f'Signed in · {plan.title()}' if supported else 'API-key sign-in · use ChatGPT for allowance tracking'}
    result = subprocess.run([find_claude(), 'auth', 'status'], capture_output=True,
                            text=True, encoding='utf-8', timeout=20,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    try:
        data = json.loads(result.stdout)
        if not isinstance(data.get('loggedIn'), bool):
            raise ValueError
    except (ValueError, AttributeError):
        raise RuntimeError('Claude Code could not report sign-in status.') from None
    if not data['loggedIn']:
        return {'signed_in': False, 'supported': False, 'text': 'Not signed in'}
    if result.returncode:
        raise RuntimeError('Claude Code sign-in check failed.')
    supported = data.get('authMethod') == 'claude.ai'
    plan = data.get('subscriptionType') or 'subscription'
    return {'signed_in': True, 'supported': supported,
            'text': f'Signed in · {plan.title()}' if supported else 'API-key / provider sign-in · use a Claude subscription'}


def change(provider, action, backend, cancel):
    if provider not in ('codex', 'claude') or action not in ('login', 'logout'):
        raise ValueError('Unknown account action')
    binary = backend.find_codex() if provider == 'codex' else find_claude()
    args = [binary, action] if provider == 'codex' else [binary, 'auth', action]
    if provider == 'claude' and action == 'login':
        args.append('--claudeai')
    # The installed client owns the browser flow and credential storage.
    process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True, encoding='utf-8',
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    import time
    deadline = time.monotonic() + (180 if action == 'login' else 30)
    try:
        while True:
            if cancel.is_set():
                raise RuntimeError('Sign-in cancelled.')
            if time.monotonic() >= deadline:
                raise RuntimeError('Sign-in timed out. Try again and finish in your browser.')
            try:
                process.communicate(timeout=0.2)
                break
            except subprocess.TimeoutExpired:
                continue
        if process.returncode:
            raise RuntimeError('The client could not complete this action. Try signing in through its VS Code extension.')
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
    return status(provider, backend)
