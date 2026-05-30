"""
Global keyboard shortcuts via Windows RegisterHotKey + native event filter.
No third-party dependencies.
"""

import ctypes
import logging
from ctypes import wintypes

from PyQt6.QtCore import QObject, pyqtSignal, QAbstractNativeEventFilter

from config import get_hotkey_config

logger = logging.getLogger(__name__)

# Win32 constants
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
WM_HOTKEY = 0x0312

VK_MAP = {}
for c in range(0x41, 0x5B):      # A-Z
    VK_MAP[chr(c)] = c
for i in range(10):               # 0-9
    VK_MAP[str(i)] = 0x30 + i
VK_MAP.update({
    "F1": 0x70, "F2": 0x71, "F3": 0x72, "F4": 0x73,
    "F5": 0x74, "F6": 0x75, "F7": 0x76, "F8": 0x77,
    "F9": 0x78, "F10": 0x79, "F11": 0x7A, "F12": 0x7B,
})

QI_MOD_MAP = {
    "Ctrl": MOD_CONTROL, "Shift": MOD_SHIFT, "Alt": MOD_ALT,
}

ACTION_SIGNALS = ["pause", "show_hide", "copy", "toggle_zh"]


# MSG struct for parsing native events
class _MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("_pad", wintypes.UINT),  # alignment padding on 64-bit
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt_x", wintypes.LONG),
        ("pt_y", wintypes.LONG),
    ]


class _HotkeyEventFilter(QAbstractNativeEventFilter):
    def __init__(self, handler):
        super().__init__()
        self._handler = handler

    def nativeEventFilter(self, event_type, message):
        try:
            msg = ctypes.cast(message, ctypes.POINTER(_MSG)).contents
            if msg.message == WM_HOTKEY:
                self._handler.handle_hotkey(int(msg.wParam))
                return True, 0
        except Exception:
            pass
        return False, 0


class GlobalHotkeys(QObject):
    """Register system-wide hotkeys and emit signals when pressed."""

    signal_pause = pyqtSignal()
    signal_show_hide = pyqtSignal()
    signal_copy = pyqtSignal()
    signal_toggle_zh = pyqtSignal()

    _SIGNAL_MAP = {
        "pause": "signal_pause",
        "show_hide": "signal_show_hide",
        "copy": "signal_copy",
        "toggle_zh": "signal_toggle_zh",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hwnd = None
        self._ids = {}
        self._next_id = 1
        self._filter = _HotkeyEventFilter(self)
        self._registered = False

    def register(self, hwnd):
        self._hwnd = hwnd
        self._do_register()

    def _do_register(self):
        if self._hwnd is None:
            return

        hk_cfg = get_hotkey_config()
        user32 = ctypes.windll.user32

        # First unregister existing
        self._unregister_ids()

        for action in ACTION_SIGNALS:
            combo_str = hk_cfg.get(action, "")
            if not combo_str:
                continue
            mod, vk = self._parse_combo(combo_str)
            if vk == 0:
                logger.warning("Could not parse '%s' for '%s'", combo_str, action)
                continue

            kid = self._next_id
            self._next_id += 1
            ok = user32.RegisterHotKey(self._hwnd, kid, mod, vk)
            if ok:
                sig_name = self._SIGNAL_MAP.get(action)
                if sig_name:
                    self._ids[kid] = getattr(self, sig_name)
            else:
                logger.warning("Failed to register %s (id=%d, may conflict with another app)",
                               combo_str, kid)

        if not self._registered:
            from PyQt6.QtWidgets import QApplication
            QApplication.instance().installNativeEventFilter(self._filter)
            self._registered = True

        logger.info("%d hotkeys registered.", len(self._ids))

    def reregister(self):
        if self._hwnd is not None:
            self._do_register()

    def _parse_combo(self, combo_str):
        parts = combo_str.split("+")
        mod = 0
        vk = 0
        for p in parts:
            p = p.strip()
            if p in QI_MOD_MAP:
                mod |= QI_MOD_MAP[p]
            elif p in VK_MAP:
                vk = VK_MAP[p]
        return mod, vk

    def _unregister_ids(self):
        user32 = ctypes.windll.user32
        for kid in list(self._ids):
            user32.UnregisterHotKey(None, kid)
        self._ids.clear()

    def unregister(self):
        self._unregister_ids()
        self._registered = False
        logger.info("Hotkeys unregistered.")

    def handle_hotkey(self, kid):
        sig = self._ids.get(kid)
        if sig:
            sig.emit()
