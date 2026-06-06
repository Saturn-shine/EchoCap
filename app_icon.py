"""EchoCap icon — loaded from pre-rendered ICO file (assets/logo.svg)."""
from PyQt6.QtGui import QIcon
from paths import ICO_PATH


def get_app_icon():
    return QIcon(ICO_PATH)


def get_tray_icon():
    return QIcon(ICO_PATH)
