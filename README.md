# Codex and Claude Usage Tracker

Separate Windows and Linux source versions. Each platform folder is self-contained; neither depends on files outside this repository.

Tracks Codex five-hour/weekly allowances and purchased credits, plus Claude five-hour/weekly allowances. Settings support selecting either account or both, login/logout, colors, background opacity, and edge resizing.

Requires Python 3.10 or newer and installed Codex and/or Claude Code clients signed in on the same computer. The tracker uses those local client sessions. Login/logout is shared with the clients. No credentials or personal settings are included.

## Windows

Install Python with Tkinter and add it to PATH. Open `Windows/Setup.cmd` once, then open `Windows/Start Widget.vbs`. Setup creates a local virtual environment and installs the required GUI dependency.

## Linux

Install Python, Tkinter, and venv using your distribution's package manager. On Ubuntu/Debian: `sudo apt install python3 python3-tk python3-venv libxcb-cursor0`.

From the Linux folder:

```sh
sh setup.sh
sh start-tracker.sh
```

Setup needs internet access. Linux window behavior depends on the desktop compositor. Native Linux desktop behavior has not yet been verified.

This independent utility does not track API billing or stop model tasks. Server usage updates may be delayed; Claude throttling displays a retry countdown.
