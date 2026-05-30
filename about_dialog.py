"""
About dialog showing version, credits, and links.
"""

import logging

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QFont, QDesktopServices
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QPushButton, QHBoxLayout
)

from paths import VERSION_PATH

logger = logging.getLogger(__name__)


def _read_version():
    try:
        with open(VERSION_PATH, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return "1.0.0"


VERSION = _read_version()

GITHUB_URL = "https://github.com/Saturn-shine/EchoCap"


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("About EchoCap")
        self.setFixedSize(420, 360)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(24, 20, 24, 20)

        title = QLabel("EchoCap")
        title_font = QFont("Segoe UI", 18)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        ver = QLabel(f"Version {VERSION}")
        ver.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ver.setStyleSheet("color: #888;")
        layout.addWidget(ver)

        desc = QLabel(
            "Real-time bilingual caption overlay for Windows.\n"
            "Live ASR + translation for streamers and creators.\n"
            "By Saturn_shine"
        )
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setWordWrap(True)
        layout.addWidget(desc)

        credits = QLabel(
            "Powered by:\n"
            "faster-whisper  ·  MarianMT  ·  PyQt6  ·  sounddevice\n\n"
            "Models:\n"
            "faster-whisper-small (MIT) — Systran / OpenAI Whisper\n"
            "opus-mt-en-zh (CC-BY-4.0) — Helsinki-NLP"
        )
        credits.setAlignment(Qt.AlignmentFlag.AlignCenter)
        credits.setStyleSheet("color: #666; font-size: 11px;")
        layout.addWidget(credits)

        layout.addStretch()

        btn_layout = QHBoxLayout()
        gh_btn = QPushButton("GitHub")
        gh_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(GITHUB_URL)))
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        close_btn.setDefault(True)
        btn_layout.addWidget(gh_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)
