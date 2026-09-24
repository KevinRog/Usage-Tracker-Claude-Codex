#!/bin/sh
set -eu
tracker_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
python3 -m venv "$tracker_dir/.venv"
"$tracker_dir/.venv/bin/python" -m pip install -r "$tracker_dir/requirements.txt"
"$tracker_dir/.venv/bin/python" -c 'import tkinter; from PySide6 import QtWidgets'
echo 'Ready. Run sh start-tracker.sh to launch the tracker.'
