"""
Global keyboard shortcuts using Windows low-level keyboard hook (WH_KEYBOARD_LL).

This approach is more reliable than RegisterHotKey (which fails when the combo
is already taken by another app) and doesn't require window focus (unlike
QShortcut).  It works in background, globally, with zero dependencies.
"""

import ctypes
import logging
import threading
from ctypes import wintypes

from PyQt6.QtCore import QObject, pyqtSignal, QTimer, QAbstractNativeEventFilter
from PyQt6.QtWidgets import QApplication

from config import get_hotkey_config

logger = logging.getLogger(__name__)

# Win32 constants
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
WM_HOTKEY = 0x0312
WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_SYSKEYDOWN = 0x0104

VK_MAP = {}
for c in range(0x41, 0x5B):      # A-Z
    VK_MAP[chr(c)] = c
for i in range(10):
    VK_MAP[str(i)] = 0x30 + i
VK_MAP.update({
    "F1": 0x70, "F2": 0x71, "F3": 0x72, "F4": 0x73,
    "F5": 0x74, "F6": 0x75, "F7": 0x76, "F8": 0x77,
    "F9": 0x78, "F10": 0x79, "F11": 0x7A, "F12": 0x7B,
})

MOD_MAP = {
    "Ctrl":  MOD_CONTROL, "Shift": MOD_SHIFT,
    "Alt":   MOD_ALT,     "Win":   MOD_WIN,
}

ACTION_SIGNALS = ["pause", "show_hide", "copy", "toggle_minimal"]


# ------------------------------------------------------------------
# Low-level keyboard hook
# ------------------------------------------------------------------

class _KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


# Thread-local reference so the callback can find the handler
_HANDLER_REF = None


def _low_level_keyboard_proc(nCode, wParam, lParam):
    """WH_KEYBOARD_LL callback — runs on a Windows hook thread."""
    if nCode >= 0 and wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
        try:
            kb = ctypes.cast(lParam, ctypes.POINTER(_KBDLLHOOKSTRUCT)).contents
            vk = kb.vkCode
            # Read modifier key states
            mods = 0
            if ctypes.windll.user32.GetAsyncKeyState(0x11) & 0x8000:  # VK_CONTROL
                mods |= MOD_CONTROL
            if ctypes.windll.user32.GetAsyncKeyState(0x10) & 0x8000:  # VK_SHIFT
                mods |= MOD_SHIFT
            if ctypes.windll.user32.GetAsyncKeyState(0x12) & 0x8000:  # VK_MENU (Alt)
                mods |= MOD_ALT
            # Don't trigger if only modifier keys are pressed
            if vk in (0x10, 0x11, 0x12, 0x5B, 0x5C):  # Shift, Ctrl, Alt, LWin, RWin
                pass
            elif _HANDLER_REF is not None:
                _HANDLER_REF._check_combo(mods, vk)
        except Exception:
            pass
    # CallNextHookEx: wrap lParam to avoid OverflowError on 64-bit
    try:
        return ctypes.windll.user32.CallNextHookEx(
            None, nCode, wParam, wintypes.LPARAM(lParam))
    except (OverflowError, ctypes.ArgumentError):
        return 0


# C function pointer type for the hook proc (LPARAM-sized return for 64-bit)
_HOOKPROC = ctypes.WINFUNCTYPE(
    wintypes.LPARAM, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
_HOOK_CALLBACK = _HOOKPROC(_low_level_keyboard_proc)


# ------------------------------------------------------------------
# MSG struct + native event filter (for Win32 WM_HOTKEY)
# ------------------------------------------------------------------

class _MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("_pad", wintypes.UINT),
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
                self._handler.handle_wm_hotkey(int(msg.wParam))
                return True, 0
        except Exception:
            pass
        return False, 0


# ------------------------------------------------------------------
# GlobalHotkeys
# ------------------------------------------------------------------

class GlobalHotkeys(QObject):
    """System-wide hotkeys via WH_KEYBOARD_LL hook.

    Also attempts Win32 RegisterHotKey as primary mechanism (lower overhead)
    and falls back to the hook for combos that fail.
    """

    signal_pause = pyqtSignal()
    signal_show_hide = pyqtSignal()
    signal_copy = pyqtSignal()
    signal_toggle_minimal = pyqtSignal()

    _SIGNAL_MAP = {
        "pause": "signal_pause",
        "show_hide": "signal_show_hide",
        "copy": "signal_copy",
        "toggle_minimal": "signal_toggle_minimal",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hwnd = None
        self._win32_ids = {}
        self._next_win32_id = 1
        self._hook_handle = None
        self._combos = {}           # (mod, vk) → pyqtSignal
        self._hook_thread_id = None
        self._poll_timer = None
        self._filter_installed = False

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, hwnd):
        """Set up hotkeys. *hwnd* is the overlay window handle."""
        global _HANDLER_REF
        self._hwnd = hwnd
        _HANDLER_REF = self
        self._reload_combos()
        # Try Win32 hotkeys first (lower CPU overhead)
        self._register_win32()
        # Always install the hook as reliable fallback
        self._install_hook()
        # Start a Qt timer to keep the hook thread's message pump alive
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._hook_poll)
        self._poll_timer.start(200)

    def reregister(self):
        """Reload config and rebind combos."""
        self._unregister_win32()
        self._reload_combos()
        self._register_win32()

    def _reload_combos(self):
        """Parse current config into (mod, vk) → signal mapping."""
        hk_cfg = get_hotkey_config()
        self._combos.clear()
        for action in ACTION_SIGNALS:
            combo_str = hk_cfg.get(action, "")
            if not combo_str:
                continue
            mod, vk = self._parse_combo(combo_str)
            if vk == 0:
                logger.warning("Bad hotkey '%s' for %s", combo_str, action)
                continue
            sig_name = self._SIGNAL_MAP.get(action)
            if sig_name:
                self._combos[(mod, vk)] = getattr(self, sig_name)
        logger.debug("Loaded %d hotkey combos from config.", len(self._combos))

    # ------------------------------------------------------------------
    # Win32 RegisterHotKey (primary)
    # ------------------------------------------------------------------

    def _register_win32(self):
        if self._hwnd is None:
            return
        user32 = ctypes.windll.user32
        hk_cfg = get_hotkey_config()
        ok = 0
        for action in ACTION_SIGNALS:
            combo_str = hk_cfg.get(action, "")
            if not combo_str:
                continue
            mod, vk = self._parse_combo(combo_str)
            if vk == 0:
                continue
            kid = self._next_win32_id
            self._next_win32_id += 1
            if user32.RegisterHotKey(self._hwnd, kid, mod, vk):
                sig_name = self._SIGNAL_MAP.get(action)
                if sig_name:
                    self._win32_ids[kid] = getattr(self, sig_name)
                ok += 1
            else:
                err = ctypes.get_last_error()
                logger.debug("Win32 RegHotKey failed for %s (err=%d) — hook fallback active.",
                             combo_str, err)
        # Install native event filter once
        if not self._filter_installed and (ok > 0):
            QApplication.instance().installNativeEventFilter(
                _HotkeyEventFilter(self))
            self._filter_installed = True
        logger.info("%d Win32 + %d hook hotkeys active.", ok, len(self._combos))

    def _unregister_win32(self):
        if self._hwnd is None:
            return
        user32 = ctypes.windll.user32
        for kid in list(self._win32_ids):
            user32.UnregisterHotKey(self._hwnd, kid)
        self._win32_ids.clear()

    # ------------------------------------------------------------------
    # Low-level keyboard hook (reliable fallback)
    # ------------------------------------------------------------------

    def _install_hook(self):
        if self._hook_handle is not None:
            return
        # Run hook in a dedicated thread so the message pump stays alive
        def _hook_thread():
            self._hook_handle = ctypes.windll.user32.SetWindowsHookExW(
                WH_KEYBOARD_LL, _HOOK_CALLBACK, None, 0)
            if not self._hook_handle:
                logger.error("Failed to install keyboard hook (err=%d)",
                             ctypes.get_last_error())
                return
            logger.debug("Low-level keyboard hook installed.")
            # Windows message pump — required for the hook to work
            msg = wintypes.MSG()
            while self._hook_handle is not None:
                ctypes.windll.user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                ctypes.windll.user32.TranslateMessage(ctypes.byref(msg))
                ctypes.windll.user32.DispatchMessageW(ctypes.byref(msg))

        t = threading.Thread(target=_hook_thread, daemon=True)
        t.start()
        self._hook_thread_id = t.ident

    def _uninstall_hook(self):
        if self._hook_handle is not None:
            ctypes.windll.user32.UnhookWindowsHookEx(self._hook_handle)
            self._hook_handle = None
        # Post a quit message to wake the hook thread's GetMessageW
        if self._hook_thread_id is not None:
            ctypes.windll.user32.PostThreadMessageW(self._hook_thread_id, 0x0012, 0, 0)
            self._hook_thread_id = None

    @staticmethod
    def _hook_poll():
        """Dummy timer callback — keeps the Qt event loop interacting with the hook."""
        pass

    # ------------------------------------------------------------------
    # Combo matching — called from hook thread → emit Qt signal
    # ------------------------------------------------------------------

    def _check_combo(self, mods: int, vk: int):
        """Called from the hook callback.  Match against registered combos."""
        sig = self._combos.get((mods, vk))
        if sig is not None:
            logger.debug("Hook hotkey: mod=0x%X vk=0x%X", mods, vk)
            # Emit the signal (thread-safe across Qt signal/slot)
            sig.emit()

    # ------------------------------------------------------------------
    # Win32 WM_HOTKEY handler (for successfully registered Win32 hotkeys)
    # ------------------------------------------------------------------

    def handle_wm_hotkey(self, kid: int):
        """Called from native event filter when WM_HOTKEY arrives."""
        sig = self._win32_ids.get(kid)
        if sig:
            sig.emit()

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_combo(combo_str):
        parts = combo_str.split("+")
        mod = 0
        vk = 0
        for p in parts:
            p = p.strip()
            if p in MOD_MAP:
                mod |= MOD_MAP[p]
            elif p in VK_MAP:
                vk = VK_MAP[p]
        return mod, vk

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def unregister(self):
        global _HANDLER_REF
        _HANDLER_REF = None
        self._unregister_win32()
        self._uninstall_hook()
        if self._poll_timer:
            self._poll_timer.stop()
            self._poll_timer = None
        logger.info("Hotkeys unregistered.")
