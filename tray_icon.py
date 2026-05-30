"""
System tray icon with pause/resume/exit controls.
Uses PyQt6's QSystemTrayIcon (no extra dependencies).
"""

import logging
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QSystemTrayIcon, QMenu, QApplication

from app_icon import get_tray_icon

logger = logging.getLogger(__name__)


class SystemTray(QSystemTrayIcon):
    """System tray for the voice caption app."""

    signal_pause = pyqtSignal(bool)
    signal_show_window = pyqtSignal()
    signal_exit = pyqtSignal()
    signal_settings = pyqtSignal()
    signal_about = pyqtSignal()
    signal_export = pyqtSignal()
    signal_toggle_click_through = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._paused = False
        self._click_through = False

        self.setIcon(get_tray_icon())
        self.setToolTip("EchoCap")

        self._menu = QMenu()

        self._pause_action = self._menu.addAction("Pause")
        self._pause_action.triggered.connect(self._toggle_pause)

        self._show_action = self._menu.addAction("Show Window")
        self._show_action.triggered.connect(self.signal_show_window.emit)

        self._menu.addSeparator()

        self._ct_action = self._menu.addAction("Click-through")
        self._ct_action.setCheckable(True)
        self._ct_action.setChecked(False)
        self._ct_action.triggered.connect(self._on_toggle_ct)

        self._menu.addSeparator()

        export_action = self._menu.addAction("Export Transcript...")
        export_action.triggered.connect(self.signal_export.emit)

        settings_action = self._menu.addAction("Settings...")
        settings_action.triggered.connect(self.signal_settings.emit)

        self._menu.addSeparator()

        about_action = self._menu.addAction("About EchoCap")
        about_action.triggered.connect(self.signal_about.emit)

        self._menu.addSeparator()

        exit_action = self._menu.addAction("Exit")
        exit_action.triggered.connect(self._do_exit)

        self.setContextMenu(self._menu)

        # Double-click toggles window visibility
        self.activated.connect(self._on_activated)

    def set_click_through(self, enabled):
        self._click_through = enabled
        self._ct_action.setChecked(enabled)

    def _toggle_pause(self):
        self._paused = not self._paused
        if self._paused:
            self._pause_action.setText("Resume")
            self.setToolTip("EchoCap - Paused")
        else:
            self._pause_action.setText("Pause")
            self.setToolTip("EchoCap")
        self.signal_pause.emit(self._paused)

    def _on_toggle_ct(self, checked):
        self._click_through = checked
        self.signal_toggle_click_through.emit(checked)

    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.signal_show_window.emit()

    def _do_exit(self):
        self.hide()
        self.signal_exit.emit()
        QApplication.instance().quit()
