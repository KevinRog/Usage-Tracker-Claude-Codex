#!/bin/sh
set -eu

tracker_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
python=python3
if [ -x "$tracker_dir/.venv/bin/python" ]; then
    python="$tracker_dir/.venv/bin/python"
fi
if ! command -v "$python" >/dev/null 2>&1; then
    echo 'Python 3 is required to run the tracker.' >&2
    exit 1
fi
if [ "${1:-}" = '--check' ]; then
    exec "$python" "$tracker_dir/usage_widget.py" "$@"
fi
if ! "$python" -c 'import tkinter' >/dev/null 2>&1; then
    echo 'Tkinter is required. Install the Python 3 Tk package for your Linux distribution.' >&2
    exit 1
fi
if ! "$python" -c 'from PySide6 import QtWidgets' >/dev/null 2>&1; then
    echo 'GUI dependencies are missing. Run sh setup.sh in the tracker folder first.' >&2
    exit 1
fi
exec "$python" "$tracker_dir/usage_widget.py" "$@"
