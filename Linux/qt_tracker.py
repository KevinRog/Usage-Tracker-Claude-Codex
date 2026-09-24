"""Composited tracker: only the painted background has variable opacity."""
import os
import queue
import threading
import time

from PySide6.QtCore import Qt, QTimer, Signal, QPoint, QRectF
from PySide6.QtGui import QColor, QPainter, QPen, QFont, QShortcut, QKeySequence
from PySide6.QtWidgets import QApplication, QWidget, QLabel, QPushButton, QHBoxLayout, QVBoxLayout, QGridLayout, QFrame

import claude_usage
from appearance import normalize
from compact_ui import format_usage, format_credits, CODEX_REFRESH_SECONDS, CLAUDE_REFRESH_SECONDS


class UsageLabel(QLabel):
    clicked = Signal()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class DragHeader(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.offset = None
        self.target = None
        self.frame_timer = QTimer(self)
        self.frame_timer.setSingleShot(True)
        self.frame_timer.setInterval(16)
        self.frame_timer.timeout.connect(self.apply_move)
        self.setCursor(Qt.CursorShape.SizeAllCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.offset = event.globalPosition().toPoint() - self.window().pos()
            event.accept()

    def mouseMoveEvent(self, event):
        if self.offset is not None:
            self.target = event.globalPosition().toPoint() - self.offset
            if not self.frame_timer.isActive():
                self.frame_timer.start()
            event.accept()

    def apply_move(self):
        if self.target is not None:
            self.window().move(self.target)
            self.target = None

    def mouseReleaseEvent(self, event):
        if self.offset is not None and event.button() == Qt.MouseButton.LeftButton:
            self.target = event.globalPosition().toPoint() - self.offset
            self.frame_timer.stop()
            self.apply_move()
            self.offset = None
            event.accept()


class Tracker(QWidget):
    def __init__(self, backend, start_workers=True):
        super().__init__()
        self.backend = backend
        self.appearance = normalize(backend.load_config().get('appearance'))
        self.setWindowTitle('Usage Tracker')
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # Keep windowOpacity at 1.0: alpha is applied only by paintEvent below.
        self.setFont(QFont('Segoe UI', 10))
        self.setMouseTracking(True)
        self.move(30, 60)
        self.tk_host = None
        self.settings_timer = QTimer(self)
        self.settings_timer.setInterval(16)
        self.settings_timer.timeout.connect(self.pump_settings)
        self.labels = {}
        self.captions = []
        self.roles = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 12)
        layout.setSpacing(9)
        self.header = DragHeader(self)
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(4)
        self.heading = QLabel('USAGE', self.header)
        self.heading.setFont(QFont('Segoe UI', 8, QFont.Weight.Bold))
        self.heading.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        header_layout.addWidget(self.heading)
        self.settings_button = self.make_button('\u2699', 'Settings', self.open_settings)
        header_layout.addWidget(self.settings_button)
        header_layout.addStretch()
        self.minimize_button = self.make_button('\u2013', 'Minimize', self.showMinimized)
        self.close_button = self.make_button('\u00d7', 'Close', self.close)
        self.close_button.setObjectName('closeButton')
        header_layout.addWidget(self.minimize_button)
        header_layout.addWidget(self.close_button)
        layout.addWidget(self.header)
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(1, 1)
        for i, name in enumerate(('Codex 5h', 'Codex week', 'Codex credits', 'Claude 5h', 'Claude week')):
            row = i if i < 3 else i + 1
            caption = QLabel(name + ':', self)
            self.captions.append(caption)
            grid.addWidget(caption, row, 0)
            value = UsageLabel('-- --', self)
            value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            value.setCursor(Qt.CursorShape.PointingHandCursor)
            value.clicked.connect(self.refresh_claude if name.startswith('Claude') else self.refresh_codex)
            grid.addWidget(value, row, 1)
            self.labels[name] = value
            self.roles[name] = 'claude' if name.startswith('Claude') else 'credits' if name.endswith('credits') else 'codex'
        self.divider = QFrame(self)
        self.divider.setFixedHeight(1)
        grid.addWidget(self.divider, 3, 0, 1, 2)
        layout.addLayout(grid)
        self.notice = QLabel('', self)
        self.notice.setFont(QFont('Segoe UI', 9))
        self.notice.setWordWrap(True)
        self.notice.hide()
        layout.addWidget(self.notice)
        self.shortcut = QShortcut(QKeySequence('S'), self)
        self.shortcut.activated.connect(self.open_settings)
        self.apply_appearance(self.appearance)
        self.show_controls(False)
        self.connection = backend.Connection()
        self.results = queue.Queue()
        self.session_results = queue.Queue()
        self.stopping = threading.Event()
        self.state = {'busy': False, 'last': 0, 'value': None, 'week': None,
                      'error': False, 'credits': None, 'credit_error': False}
        self.claude_results = queue.Queue()
        self.claude_state = {'busy': False, 'next': 0, 'retry_at': 0, 'updated': 0,
                             'five_hour': None, 'seven_day': None, 'error': ''}
        self.account_changes = {}
        self.signed_out = {'codex': False, 'claude': False}
        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.tick)
        self.adjustSize()
        self.resize(340, self.height())
        if start_workers:
            watcher = backend.SessionWatcher()
            def watch():
                while not self.stopping.is_set():
                    try:
                        self.session_results.put(watcher.poll())
                    except (OSError, ValueError, TypeError):
                        pass
                    self.stopping.wait(1)
            threading.Thread(target=watch, daemon=True).start()
            self.timer.start()
            self.tick()

    def resize_edges(self, point):
        """Keep resize handles inside the painted, clickable border."""
        edges = Qt.Edge(0)
        margin = 7
        if point.x() < margin:
            edges |= Qt.Edge.LeftEdge
        elif point.x() >= self.width() - margin:
            edges |= Qt.Edge.RightEdge
        if point.y() < margin:
            edges |= Qt.Edge.TopEdge
        elif point.y() >= self.height() - margin:
            edges |= Qt.Edge.BottomEdge
        return edges

    def mouseMoveEvent(self, event):
        edges = self.resize_edges(event.position().toPoint())
        cursors = {
            Qt.Edge.LeftEdge: Qt.CursorShape.SizeHorCursor,
            Qt.Edge.RightEdge: Qt.CursorShape.SizeHorCursor,
            Qt.Edge.TopEdge: Qt.CursorShape.SizeVerCursor,
            Qt.Edge.BottomEdge: Qt.CursorShape.SizeVerCursor,
            Qt.Edge.TopEdge | Qt.Edge.LeftEdge: Qt.CursorShape.SizeFDiagCursor,
            Qt.Edge.BottomEdge | Qt.Edge.RightEdge: Qt.CursorShape.SizeFDiagCursor,
            Qt.Edge.TopEdge | Qt.Edge.RightEdge: Qt.CursorShape.SizeBDiagCursor,
            Qt.Edge.BottomEdge | Qt.Edge.LeftEdge: Qt.CursorShape.SizeBDiagCursor,
        }
        self.setCursor(cursors.get(edges, Qt.CursorShape.ArrowCursor))
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            edges = self.resize_edges(event.position().toPoint())
            if edges and self.windowHandle() and self.windowHandle().startSystemResize(edges):
                event.accept()
                return
        super().mousePressEvent(event)

    def make_button(self, text, tooltip, action):
        button = QPushButton(text, self.header)
        button.setToolTip(tooltip)
        button.setFixedSize(28, 26)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(action)
        policy = button.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        button.setSizePolicy(policy)
        return button

    def show_controls(self, visible):
        for button in (self.settings_button, self.minimize_button, self.close_button):
            button.setVisible(visible)

    def enterEvent(self, event):
        self.show_controls(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        if self.header.offset is None:
            self.show_controls(False)
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        background = QColor(self.appearance['colors']['background'])
        background.setAlphaF(self.appearance['opacity'])
        # Nonzero alpha across the interior keeps the whole panel hit-testable.
        painter.setBrush(background)
        painter.setPen(QPen(QColor(self.appearance['colors']['border']), 1))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 5, 5)

    def apply_appearance(self, data):
        self.appearance = normalize(data)
        c = self.appearance['colors']
        self.setStyleSheet(
            f'QLabel {{ background: transparent; color: {c["text"]}; }}'
            f'QPushButton {{ background: transparent; color: {c["button_text"]}; border: none; border-radius: 3px; font-size: 17px; }}'
            f'QPushButton:hover, QPushButton:focus {{ background: {c["hover"]}; color: {c["hover_text"]}; }}'
            f'QPushButton#closeButton:hover {{ background: {c["close_hover"]}; color: {c["hover_text"]}; }}')
        self.heading.setStyleSheet(f'color: {c["muted"]}; background: transparent;')
        self.divider.setStyleSheet(f'background: {c["divider"]};')
        self.notice.setStyleSheet(f'color: {c["warning"]}; background: transparent;')
        for name, label in self.labels.items():
            label.setStyleSheet(f'color: {c[self.roles[name]]}; background: transparent;')
        for caption, (name, label) in zip(self.captions, self.labels.items()):
            visible = ('claude' if name.startswith('Claude') else 'codex') in self.appearance['providers']
            caption.setVisible(visible)
            label.setVisible(visible)
        self.divider.setVisible(len(self.appearance['providers']) == 2)
        if 'codex' not in self.appearance['providers']:
            self.notice.hide()
        self.update()

    def set_reading(self, name, text, role):
        self.labels[name].setText(text)
        if self.roles[name] != role:
            self.roles[name] = role
            self.labels[name].setStyleSheet(f'color: {self.appearance["colors"][role]}; background: transparent;')

    def open_settings(self):
        # Keep the existing settings/account controls; only the tracker needs
        # a per-pixel composited surface. Tk is pumped on the same UI thread.
        if self.tk_host is None:
            import tkinter as tk
            from appearance import Theme
            self.tk_host = tk.Tk()
            self.tk_host.withdraw()
            self.tk_host._theme = Theme(self.tk_host, self.appearance, renderer=self.apply_appearance)
            self.tk_host._account_changed = lambda provider, connected: self.account_changes.update({provider: connected})
        self.tk_host.geometry(f'+{max(0, self.x())}+{max(0, self.y())}')
        from settings_ui import open_settings
        open_settings(self.tk_host, self.backend)
        self.settings_timer.start()

    def pump_settings(self):
        if self.tk_host is not None:
            self.tk_host.update()
            dialog = getattr(self.tk_host, '_settings_dialog', None)
            if dialog is None or not dialog.winfo_exists():
                self.settings_timer.stop()

    def refresh_codex(self):
        if 'codex' not in self.appearance['providers'] or self.signed_out['codex'] or self.state['busy']:
            return
        self.state.update(busy=True, last=time.time())
        def work():
            try:
                self.results.put((self.connection.refresh_snapshot(), False))
            except Exception:
                self.connection.close()
                self.results.put((None, True))
        threading.Thread(target=work, daemon=True).start()

    def refresh_claude(self):
        now = time.time()
        if 'claude' not in self.appearance['providers'] or self.signed_out['claude'] or self.claude_state['busy'] or now < self.claude_state['retry_at']:
            return
        self.claude_state.update(busy=True, next=now + CLAUDE_REFRESH_SECONDS)
        def work():
            try:
                self.claude_results.put((claude_usage.fetch_usage(), '', CLAUDE_REFRESH_SECONDS))
            except claude_usage.UsageError as exc:
                self.claude_results.put((None, str(exc), exc.retry_after))
            except Exception:
                self.claude_results.put((None, 'Claude usage unavailable. Check sign-in in Settings.', 60))
        threading.Thread(target=work, daemon=True).start()

    def tick(self):
        state, cs = self.state, self.claude_state
        while not self.results.empty():
            value, error = self.results.get_nowait()
            state.update(busy=False, error=error, credit_error=error)
            if not error:
                state['value'], state['credits'], state['week'] = value
        if 'codex' in self.account_changes and not state['busy']:
            self.signed_out['codex'] = not self.account_changes.pop('codex')
            self.connection.close()
            state.update(value=None, week=None, credits=None, last=0, error=False, credit_error=False)
        completed, latest = False, None
        while not self.session_results.empty():
            done, reading = self.session_results.get_nowait()
            completed = completed or done
            if reading and (latest is None or reading[0] > latest[0]):
                latest = reading
        if latest and not self.signed_out['codex']:
            state.update(value=latest[1], error=False)
        if completed or time.time()-state['last'] >= CODEX_REFRESH_SECONDS:
            self.refresh_codex()
        for name, value, stale in (('Codex 5h', state['value'], state['error']),
                                   ('Codex week', state['week'], state['credit_error'])):
            text = 'Signed out' if self.signed_out['codex'] else format_usage(value) if value else 'Unavailable'
            self.set_reading(name, text + (' *' if stale else ''),
                             'warning' if stale or value is None or value[0] <= 10 else 'codex')
        self.set_reading('Codex credits', 'Signed out' if self.signed_out['codex'] else format_credits(state['credits'], state['credit_error']),
                         'warning' if state['credit_error'] or state['credits'] is None else 'credits')
        value = state['value']
        low = bool('codex' in self.appearance['providers'] and value and value[0] <= 10 and value[1] > time.time())
        if low:
            self.notice.setText(f'Codex five-hour allowance low: {value[0]:g}% left')
        if self.notice.isHidden() == low:
            self.notice.setVisible(low)
        while not self.claude_results.empty():
            snapshot, error, delay = self.claude_results.get_nowait()
            now = time.time()
            cs.update(busy=False, error=error, next=now+delay, retry_at=now+delay if delay > CLAUDE_REFRESH_SECONDS else 0)
            if snapshot is not None:
                cs.update(snapshot, updated=now)
        if 'claude' in self.account_changes and not cs['busy']:
            self.signed_out['claude'] = not self.account_changes.pop('claude')
            cs.update(five_hour=None, seven_day=None, next=0, retry_at=0, error='')
        if time.time() >= cs['next']:
            self.refresh_claude()
        stale = bool(cs['error']) or time.time()-cs['updated'] > 2*CLAUDE_REFRESH_SECONDS
        for label, key in (('Claude 5h', 'five_hour'), ('Claude week', 'seven_day')):
            value = cs[key]
            text = format_usage(value)+(' *' if stale else '') if value else 'Checking...' if cs['busy'] else 'Unavailable'
            if value is None and cs['retry_at'] > time.time():
                minutes = max(1, int((cs['retry_at'] - time.time() + 59) // 60))
                text = f'Retry in {minutes}m'
            if value is None and 'sign' in cs['error'].lower():
                text = 'Check sign-in'
            self.labels[label].setToolTip(cs['error'] or '')
            self.set_reading(label, 'Signed out' if self.signed_out['claude'] else text,
                             'warning' if stale or value is None or value[0] <= 10 else 'claude')

    def closeEvent(self, event):
        self.timer.stop()
        self.settings_timer.stop()
        self.stopping.set()
        self.connection.close()
        if self.tk_host is not None:
            self.tk_host.destroy()
            self.tk_host = None
        event.accept()


def run(backend):
    mutex = None
    if os.name == 'nt':
        import ctypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
        kernel.CreateMutexW.restype = ctypes.c_void_p
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        mutex = kernel.CreateMutexW(None, False, 'Local\\CodexClaudeUsageTracker')
        if mutex and ctypes.get_last_error() == 183:
            kernel.CloseHandle(mutex)
            return
    try:
        app = QApplication.instance() or QApplication([])
        widget = Tracker(backend)
        widget.show()
        app.exec()
    finally:
        if mutex:
            kernel.CloseHandle(mutex)
