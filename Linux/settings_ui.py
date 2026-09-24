"""Appearance and shared-client account settings."""
import copy
import queue
import threading
import tkinter as tk
from tkinter import colorchooser

import accounts
from appearance import COLORS, normalize


def open_settings(parent, backend):
    existing = getattr(parent, '_settings_dialog', None)
    if existing is not None and existing.winfo_exists():
        existing.lift()
        return existing
    theme = parent._theme
    saved = copy.deepcopy(theme.data)
    draft = copy.deepcopy(saved)
    dialog = tk.Toplevel(parent)
    parent._settings_dialog = dialog
    dialog.title('Usage Tracker settings')
    dialog.attributes('-topmost', True)
    dialog.resizable(False, False)
    theme.bind(dialog, background='background')
    cancel = threading.Event()
    dialog.bind('<Destroy>', lambda event: cancel.set() if event.widget is dialog else None, add='+')
    results = queue.Queue()
    jobs = set()
    cards = {}
    swatches = {}
    poll_timer = None

    def frame(master, **kwargs):
        return theme.bind(tk.Frame(master, **kwargs), background='background')

    def label(master, text='', muted=False, **kwargs):
        kwargs.setdefault('font', ('Segoe UI', 9))
        return theme.bind(tk.Label(master, text=text, **kwargs),
                          background='background', foreground='muted' if muted else 'text')

    def button(master, text, command, **kwargs):
        widget = tk.Button(master, text=text, command=command, font=('Segoe UI', 9),
                           relief='flat', bd=0, padx=12, pady=6, cursor='hand2', **kwargs)
        theme.bind(widget, background='button', foreground='button_text',
                   activebackground='hover', activeforeground='hover_text', disabledforeground='muted')
        widget.bind('<Enter>', lambda event: widget.configure(bg=theme.color('hover')))
        widget.bind('<Leave>', lambda event: widget.configure(bg=theme.color(theme.widgets[widget]['background'])))
        return widget

    body = frame(dialog, padx=20, pady=16)
    body.pack(fill='both', expand=True)
    title = label(body, 'Settings', anchor='w')
    title.configure(font=('Segoe UI', 16, 'bold'))
    title.pack(fill='x')
    label(body, 'Appearance and connected accounts', muted=True, anchor='w').pack(fill='x', pady=(2, 14))
    tabs = frame(body)
    tabs.pack(fill='x', pady=(0, 14))
    content = frame(body)
    content.pack(fill='both', expand=True)
    pages = {name: frame(content) for name in ('Appearance', 'Accounts')}
    tab_buttons = {}

    def select(name):
        for key, page in pages.items():
            page.grid(row=0, column=0, sticky='nsew')
            if key != name:
                page.grid_remove()
            theme.bind(tab_buttons[key], background='hover' if key == name else 'button',
                       foreground='hover_text' if key == name else 'button_text')
        dialog.update_idletasks()

    for name in pages:
        tab_buttons[name] = button(tabs, name, lambda name=name: select(name), width=19)
        tab_buttons[name].pack(side='left', padx=(0, 8))

    appearance = pages['Appearance']
    label(appearance, 'Accounts to display', anchor='w').pack(fill='x')
    choices = frame(appearance)
    choices.pack(fill='x', pady=(5, 12))
    provider_vars = {name: tk.BooleanVar(value=name in draft['providers']) for name in ('codex', 'claude')}

    def choose_provider(name):
        selected = [key for key, var in provider_vars.items() if var.get()]
        if not selected:
            provider_vars[name].set(True)
            return
        draft['providers'] = selected
        preview()

    for name, variable in provider_vars.items():
        check = tk.Checkbutton(choices, text='ChatGPT / Codex' if name == 'codex' else 'Claude',
                               variable=variable, command=lambda name=name: choose_provider(name),
                               font=('Segoe UI', 9), bd=0, highlightthickness=0)
        theme.bind(check, background='background', foreground='text', selectcolor='panel',
                   activebackground='background', activeforeground='text')
        check.pack(side='left', padx=(0, 20))
    label(appearance, 'Transparency', anchor='w').pack(fill='x')
    opacity = tk.IntVar(value=round(draft['opacity'] * 100))
    opacity_text = tk.StringVar()

    def preview(*_):
        draft['opacity'] = opacity.get() / 100
        theme.apply(draft)
        opacity_text.set(f'Background opacity   {opacity.get()}%')
        for role, swatch in swatches.items():
            swatch.configure(text=draft['colors'][role].upper(), bg=draft['colors'][role],
                             fg=contrast(draft['colors'][role]))

    label(appearance, textvariable=opacity_text, muted=True, anchor='w').pack(fill='x', pady=(5, 0))
    slider = tk.Scale(appearance, from_=40, to=100, orient='horizontal', variable=opacity,
                      showvalue=False, command=preview, highlightthickness=0, bd=0, sliderlength=24)
    theme.bind(slider, background='background', foreground='text', troughcolor='panel', activebackground='hover')
    slider.pack(fill='x')
    label(appearance, 'Only the background fades. Text and controls stay opaque and clickable.', muted=True,
          anchor='w').pack(fill='x', pady=(3, 12))
    label(appearance, 'Colors', anchor='w').pack(fill='x', pady=(0, 7))
    palette = frame(appearance)
    palette.pack(fill='x')

    def choose(role):
        color = colorchooser.askcolor(draft['colors'][role], parent=dialog, title=COLORS[role][0])[1]
        if color:
            draft['colors'][role] = color
            preview()

    for index, (role, (name, _)) in enumerate(COLORS.items()):
        cell = frame(palette)
        cell.grid(row=index // 2, column=index % 2, sticky='ew', padx=(0, 14) if index % 2 == 0 else 0, pady=3)
        label(cell, name, anchor='w', width=21).pack(side='left')
        swatch = tk.Button(cell, width=8, font=('Consolas', 9), relief='flat', bd=0,
                           pady=4, command=lambda role=role: choose(role), cursor='hand2')
        swatch.pack(side='right')
        swatches[role] = swatch

    account_page = pages['Accounts']
    label(account_page, 'These sign-ins are shared with your installed clients.', anchor='w').pack(fill='x')
    label(account_page, 'Logging out here also signs out the corresponding local client.\nNo API keys are needed for subscription limits.',
          muted=True, justify='left', anchor='w').pack(fill='x', pady=(4, 14))

    def run_job(provider, action='status'):
        if provider in jobs:
            return
        jobs.add(provider)
        card = cards[provider]
        card['text'].set('Finish signing in in your browser…' if action == 'login' else
                         'Signing out…' if action == 'logout' else 'Checking sign-in…')
        for widget in card['buttons']:
            widget.configure(state='disabled')
        def work():
            try:
                info = accounts.status(provider, backend) if action == 'status' else accounts.change(provider, action, backend, cancel)
                results.put((provider, info, None))
            except Exception as exc:
                # Account helpers return safe messages and never surface auth output.
                text = str(exc) if isinstance(exc, (FileNotFoundError, RuntimeError)) else 'Connection check failed. Try again.'
                results.put((provider, None, (text, isinstance(exc, FileNotFoundError))))
        threading.Thread(target=work, daemon=True).start()

    for provider, title, detail in (
            ('codex', 'ChatGPT / Codex', 'Five-hour allowance, weekly allowance, and purchased credits.'),
            ('claude', 'Claude', 'Five-hour and weekly subscription allowance.')):
        card = frame(account_page, padx=14, pady=14, highlightthickness=1)
        theme.bind(card, background='panel', highlightbackground='border', highlightcolor='border')
        card.pack(fill='x', pady=(0, 12))
        heading = label(card, title, anchor='w')
        heading.configure(font=('Segoe UI', 12, 'bold'))
        theme.bind(heading, background='panel')
        heading.pack(fill='x')
        text = tk.StringVar(value='Checking sign-in…')
        state_label = label(card, textvariable=text, anchor='w', justify='left', wraplength=480)
        theme.bind(state_label, background='panel')
        state_label.pack(fill='x', pady=(8, 4))
        detail_label = label(card, detail, muted=True, anchor='w', wraplength=480, justify='left')
        theme.bind(detail_label, background='panel')
        detail_label.pack(fill='x')
        actions = frame(card)
        theme.bind(actions, background='panel')
        actions.pack(fill='x', pady=(12, 0))
        login = button(actions, 'Log in', lambda provider=provider: run_job(provider, 'login'))
        logout = button(actions, 'Log out', lambda provider=provider: run_job(provider, 'logout'))
        refresh = button(actions, 'Check status', lambda provider=provider: run_job(provider))
        refresh.pack(side='left', padx=(0, 8))
        cards[provider] = {'text': text, 'buttons': (login, logout, refresh)}

    feedback = tk.StringVar(value='Changes preview instantly. Save to keep them.')
    label(body, textvariable=feedback, muted=True, anchor='w', wraplength=540).pack(fill='x', pady=(14, 8))
    footer = frame(body)
    footer.pack(fill='x')

    def close(keep=False):
        cancel.set()
        if poll_timer is not None:
            dialog.after_cancel(poll_timer)
        if not keep:
            theme.apply(saved)
        dialog.destroy()

    def save():
        try:
            config = backend.load_config()
            config['appearance'] = normalize(draft)
            # These fields no longer serve any feature in the tracker.
            config.pop('anthropic_api_key', None)
            config.pop('chatgpt_credits_left', None)
            backend.save_config(config)
            close(keep=True)
        except OSError:
            feedback.set('Could not save settings. Check that your settings folder is writable.')

    def defaults():
        draft.clear()
        draft.update(normalize({}))
        for variable in provider_vars.values():
            variable.set(True)
        opacity.set(100)
        preview()

    button(footer, 'Restore defaults', defaults).pack(side='left')
    button(footer, 'Save', save).pack(side='right')
    button(footer, 'Cancel', close).pack(side='right', padx=8)
    dialog.protocol('WM_DELETE_WINDOW', close)
    dialog.bind('<Escape>', lambda event: close())

    def receive():
        nonlocal poll_timer
        if cancel.is_set():
            return
        while not results.empty():
            provider, info, error = results.get_nowait()
            jobs.discard(provider)
            card = cards[provider]
            login, logout, refresh = card['buttons']
            refresh.configure(state='normal')
            if error:
                card['text'].set(error[0])
                login.pack_forget()
                logout.pack_forget()
            else:
                card['text'].set(info['text'])
                visible, hidden = (logout, login) if info['signed_in'] else (login, logout)
                hidden.pack_forget()
                visible.pack(side='left', padx=(0, 8), before=refresh)
                visible.configure(state='normal')
                callback = getattr(parent, '_account_changed', None)
                if callback:
                    callback(provider, info['supported'])
        poll_timer = dialog.after(100, receive)

    # Reserve the larger page size so changing tabs does not jump the window.
    for page in pages.values():
        page.grid(row=0, column=0, sticky='nsew')
    dialog.update_idletasks()
    content.configure(width=max(p.winfo_reqwidth() for p in pages.values()),
                      height=max(p.winfo_reqheight() for p in pages.values()))
    content.grid_propagate(False)
    select('Appearance')
    preview()
    dialog.update_idletasks()
    dialog.geometry(f'+{max(0, min(parent.winfo_x()+25, dialog.winfo_screenwidth()-dialog.winfo_reqwidth()-20))}+'
                    f'{max(0, min(parent.winfo_y()+25, dialog.winfo_screenheight()-dialog.winfo_reqheight()-60))}')
    for provider in cards:
        run_job(provider)
    receive()
    return dialog


def contrast(color):
    r, g, b = (int(color[i:i+2], 16) for i in (1, 3, 5))
    return '#101820' if 0.2126*r + 0.7152*g + 0.0722*b > 150 else '#ffffff'
