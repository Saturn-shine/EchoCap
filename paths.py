"""
Application paths — handles frozen (PyInstaller) vs. development environments.

In a PyInstaller --onefile bundle, the executable is extracted to a temporary
directory (sys._MEIPASS) which is READ-ONLY. All writable files (config, logs,
transcripts, generated icon) must go to a user-writable location.
"""

import os
import sys


def _get_data_dir():
    """Return the writable data directory, creating it if needed.

    - PyInstaller bundle: %APPDATA%/EchoCap
    - Development: same directory as this source file
    """
    if getattr(sys, 'frozen', False):
        data_dir = os.path.join(
            os.environ.get("APPDATA", os.path.expanduser("~")), "EchoCap"
        )
    else:
        data_dir = os.path.dirname(os.path.abspath(__file__))
    os.makedirs(data_dir, exist_ok=True)
    return data_dir


#: Directory containing this source file / extracted bundle (read-only in frozen mode).
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

#: Writable data directory.
DATA_DIR = _get_data_dir()

# Writable paths — use these for any file the app creates or modifies
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")
LOG_PATH = os.path.join(DATA_DIR, "app.log")
TRANSCRIPTS_PATH = os.path.join(DATA_DIR, "transcripts.txt")
ICO_PATH = os.path.join(DATA_DIR, "app_icon.ico")

# Read-only bundled paths — safe to read in both dev and frozen modes
VERSION_PATH = os.path.join(BASE_DIR, "VERSION")
