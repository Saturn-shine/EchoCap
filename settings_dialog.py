"""
Settings dialog with tabbed pages for all configuration sections.
"""

import copy

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QDialog, QTabWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QSpinBox, QDoubleSpinBox, QSlider,
    QComboBox, QCheckBox, QPushButton, QFileDialog, QColorDialog,
    QGroupBox, QDialogButtonBox, QApplication, QFontComboBox,
    QMessageBox, QTextEdit
)

from paths import TRANSCRIPTS_PATH
from config import DEFAULT_CONFIG, _deep_merge, load_config, save_config
from vu_meter import VUMeterWidget, VUMeterPollWorker

# Modifier constants for hotkey parsing
MOD_CTRL = 0x0002
MOD_SHIFT = 0x0004
MOD_ALT = 0x0001

LANGUAGES = [
    ("Auto-detect", ""),
    ("English", "en"),
    ("Chinese (Simplified)", "zh-CN"),
    ("Chinese (Traditional)", "zh-TW"),
    ("Japanese", "ja"),
    ("Korean", "ko"),
    ("French", "fr"),
    ("German", "de"),
    ("Spanish", "es"),
    ("Russian", "ru"),
    ("Arabic", "ar"),
    ("Portuguese", "pt"),
    ("Italian", "it"),
    ("Dutch", "nl"),
    ("Polish", "pl"),
    ("Turkish", "tr"),
    ("Vietnamese", "vi"),
    ("Thai", "th"),
    ("Hindi", "hi"),
]

MODIFIER_COMBOS = [
    ("None", 0),
    ("Ctrl", MOD_CTRL),
    ("Alt", MOD_ALT),
    ("Shift", MOD_SHIFT),
    ("Ctrl+Shift", MOD_CTRL | MOD_SHIFT),
    ("Ctrl+Alt", MOD_CTRL | MOD_ALT),
    ("Shift+Alt", MOD_SHIFT | MOD_ALT),
]

# ---------------------------------------------------------------------------
# Helper widgets
# ---------------------------------------------------------------------------

class _ColorButton(QPushButton):
    """PushButton that shows a color swatch and opens QColorDialog on click."""

    def __init__(self, color_hex, parent=None):
        super().__init__(parent)
        self._color = color_hex
        self.setFixedSize(36, 22)
        self.clicked.connect(self._pick)
        self._update_swatch()

    def _pick(self):
        c = QColorDialog.getColor(QColor(self._color), self, "Pick color")
        if c.isValid():
            self._color = c.name()
            self._update_swatch()

    def _update_swatch(self):
        self.setStyleSheet(
            f"QPushButton {{ background-color: {self._color}; "
            f"border: 1px solid #888; border-radius: 3px; }}"
            f"QPushButton:hover {{ border: 1px solid #fff; }}"
        )

    def hex(self):
        return self._color


class _PathRow(QHBoxLayout):
    """LineEdit + Browse button for directory paths."""

    def __init__(self, path, parent=None):
        super().__init__()
        self._edit = QLineEdit(path, parent)
        self._edit.setMinimumWidth(300)
        btn = QPushButton("...", parent)
        btn.setFixedWidth(30)
        btn.clicked.connect(self._browse)
        self.addWidget(self._edit)
        self.addWidget(btn)

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self._edit, "Select directory")
        if d:
            self._edit.setText(d)

    def text(self):
        return self._edit.text()


# ---------------------------------------------------------------------------
# Tab pages
# ---------------------------------------------------------------------------

class AudioTab(QGroupBox):
    def __init__(self, cfg, parent=None):
        super().__init__("Audio", parent)
        layout = QFormLayout(self)

        # Device picker
        self._device_combo = QComboBox()
        self._device_combo.addItem("(default)", None)
        try:
            import sounddevice as sd
            for idx, d in enumerate(sd.query_devices()):
                if d['max_input_channels'] > 0:
                    label = f"[{idx}] {d['name']}"
                    self._device_combo.addItem(label, idx)
        except Exception:
            pass
        cur = cfg["audio"].get("device")
        if cur is not None:
            for i in range(self._device_combo.count()):
                if self._device_combo.itemData(i) == cur:
                    self._device_combo.setCurrentIndex(i)
                    break
        layout.addRow("Input device:", self._device_combo)

        self._rate_spin = QSpinBox()
        self._rate_spin.setRange(8000, 48000)
        self._rate_spin.setSingleStep(1000)
        self._rate_spin.setValue(cfg["audio"].get("sample_rate", 16000))
        layout.addRow("Sample rate:", self._rate_spin)

        self._vad_mode = QComboBox()
        self._vad_mode.addItems(["0 (least aggressive)", "1", "2", "3 (most aggressive)"])
        self._vad_mode.setCurrentIndex(cfg["audio"].get("vad_mode", 1))
        layout.addRow("VAD sensitivity:", self._vad_mode)

        self._silence_spin = QDoubleSpinBox()
        self._silence_spin.setRange(0.2, 3.0)
        self._silence_spin.setSingleStep(0.1)
        self._silence_spin.setDecimals(1)
        self._silence_spin.setValue(cfg["audio"].get("silence_timeout_s", 0.7))
        self._silence_spin.setSuffix(" s")
        layout.addRow("Silence timeout:", self._silence_spin)

        self._vu_meter = VUMeterWidget()
        layout.addRow("Mic level:", self._vu_meter)

    @property
    def vu_meter_widget(self):
        return self._vu_meter

    def apply(self, cfg):
        idx = self._device_combo.currentData()
        cfg["audio"]["device"] = idx
        cfg["audio"]["sample_rate"] = self._rate_spin.value()
        cfg["audio"]["vad_mode"] = self._vad_mode.currentIndex()
        cfg["audio"]["silence_timeout_s"] = self._silence_spin.value()


class ASRTab(QGroupBox):
    def __init__(self, cfg, parent=None):
        super().__init__("ASR", parent)
        layout = QFormLayout(self)

        self._model_row = _PathRow(cfg["asr"].get("model_size", ""))
        layout.addRow("Model path:", self._model_row)

        self._device = QComboBox()
        self._device.addItems(["cuda", "cpu"])
        self._device.setCurrentText(cfg["asr"].get("device", "cuda"))
        layout.addRow("Device:", self._device)

        self._compute = QComboBox()
        self._compute.addItems(["float16", "int8_float16", "int8", "auto"])
        self._compute.setCurrentText(cfg["asr"].get("compute_type", "float16"))
        layout.addRow("Compute type:", self._compute)

        self._hf_ep = QLineEdit(cfg["asr"].get("hf_endpoint", ""))
        layout.addRow("HF endpoint:", self._hf_ep)

    def apply(self, cfg):
        cfg["asr"]["model_size"] = self._model_row.text()
        cfg["asr"]["device"] = self._device.currentText()
        cfg["asr"]["compute_type"] = self._compute.currentText()
        cfg["asr"]["hf_endpoint"] = self._hf_ep.text() or None


class TranslateTab(QGroupBox):
    def __init__(self, cfg, parent=None):
        super().__init__("Translate", parent)
        layout = QFormLayout(self)

        self._src = QComboBox()
        self._src.setEditable(True)
        cur_src = cfg["translate"].get("source", "en")
        selected = 0
        for i, (name, code) in enumerate(LANGUAGES):
            self._src.addItem(f"{name}  ({code})" if code else name, code)
            if code == cur_src:
                selected = i
        self._src.setCurrentIndex(selected)
        layout.addRow("Source lang:", self._src)

        self._tgt = QComboBox()
        self._tgt.setEditable(True)
        cur_tgt = cfg["translate"].get("target", "zh-CN")
        selected = 0
        for i, (name, code) in enumerate(LANGUAGES):
            if code:
                self._tgt.addItem(f"{name}  ({code})", code)
                if code == cur_tgt:
                    selected = i
        self._tgt.setCurrentIndex(selected)
        layout.addRow("Target lang:", self._tgt)

        self._model_row = _PathRow(cfg["translate"].get("model_path", ""))
        layout.addRow("Model path:", self._model_row)

        note = QLabel(
            "Note: Language selection is not yet functional.\n"
            "Currently hard-coded to English → Chinese (Simplified).\n"
            "Multi-language support is planned for a future release.")
        note.setStyleSheet("color: #cc8800; font-size: 11px; padding-top: 6px;")
        note.setWordWrap(True)
        layout.addRow(note)

    def apply(self, cfg):
        src_data = self._src.currentData()
        tgt_data = self._tgt.currentData()
        # currentData() may be "" (for Auto-detect) which is valid — check via index
        if self._src.currentIndex() == 0:  # Auto-detect
            cfg["translate"]["source"] = ""
        else:
            cfg["translate"]["source"] = src_data if src_data else self._src.currentText().strip()
        if tgt_data:
            cfg["translate"]["target"] = tgt_data
        else:
            cfg["translate"]["target"] = self._tgt.currentText().strip()
        cfg["translate"]["model_path"] = self._model_row.text() or None


class UITab(QGroupBox):
    def __init__(self, cfg, parent=None):
        super().__init__("UI", parent)
        layout = QFormLayout(self)

        ui = cfg["ui"]

        self._font_en = QSpinBox()
        self._font_en.setRange(14, 60)
        self._font_en.setValue(ui.get("font_size_en", 26))
        layout.addRow("EN font size:", self._font_en)

        self._font_zh = QSpinBox()
        self._font_zh.setRange(12, 50)
        self._font_zh.setValue(ui.get("font_size_zh", 20))
        layout.addRow("ZH font size:", self._font_zh)

        self._color_en = _ColorButton(ui.get("text_color_en", "#FFFFFF"))
        layout.addRow("EN color:", self._color_en)

        self._color_zh = _ColorButton(ui.get("text_color_zh", "#FFD700"))
        layout.addRow("ZH color:", self._color_zh)

        self._bg_opacity = QSlider(Qt.Orientation.Horizontal)
        self._bg_opacity.setRange(10, 90)
        self._bg_opacity.setValue(int(ui.get("bg_opacity", 0.55) * 100))
        self._bg_val = QLabel(f"{self._bg_opacity.value()}%")
        self._bg_opacity.valueChanged.connect(
            lambda v: self._bg_val.setText(f"{v}%"))
        row = QHBoxLayout()
        row.addWidget(self._bg_opacity)
        row.addWidget(self._bg_val)
        layout.addRow("BG opacity:", row)

        self._fade_spin = QDoubleSpinBox()
        self._fade_spin.setRange(0, 30)
        self._fade_spin.setValue(ui.get("fade_out_sec", 6.0))
        self._fade_spin.setSuffix(" s")
        layout.addRow("Fade-out after:", self._fade_spin)

        self._font_family = QFontComboBox()
        cur_font = QFont(ui.get("font_family", "Microsoft YaHei"))
        self._font_family.setCurrentFont(cur_font)
        layout.addRow("Font family:", self._font_family)

        self._text_align = QComboBox()
        self._text_align.addItems(["Left", "Center", "Right"])
        cur_align = ui.get("text_align", "left")
        align_map = {"left": 0, "center": 1, "right": 2}
        self._text_align.setCurrentIndex(align_map.get(cur_align, 0))
        layout.addRow("Text alignment:", self._text_align)

        self._click_through = QCheckBox()
        self._click_through.setChecked(ui.get("click_through", False))
        layout.addRow("Click-through:", self._click_through)

        self._auto_start = QCheckBox()
        self._auto_start.setChecked(ui.get("auto_start", False))
        layout.addRow("Start with Windows:", self._auto_start)

    def apply(self, cfg):
        ui = cfg["ui"]
        ui["font_size_en"] = self._font_en.value()
        ui["font_size_zh"] = self._font_zh.value()
        ui["text_color_en"] = self._color_en.hex()
        ui["text_color_zh"] = self._color_zh.hex()
        ui["bg_opacity"] = self._bg_opacity.value() / 100.0
        ui["fade_out_sec"] = self._fade_spin.value()
        ui["font_family"] = self._font_family.currentFont().family()
        align_map = {0: "left", 1: "center", 2: "right"}
        ui["text_align"] = align_map.get(self._text_align.currentIndex(), "left")
        ui["click_through"] = self._click_through.isChecked()
        ui["auto_start"] = self._auto_start.isChecked()


class HistoryTab(QGroupBox):
    def __init__(self, parent=None):
        super().__init__("History", parent)
        layout = QVBoxLayout(self)

        info = QLabel("View and manage saved transcript history.")
        info.setStyleSheet("color: #888;")
        layout.addWidget(info)

        self._text = QTextEdit()
        self._text.setReadOnly(True)
        self._text.setStyleSheet(
            "QTextEdit { background: #1e1e1e; color: #ccc; border: 1px solid #444; }")
        layout.addWidget(self._text)

        btn_row = QHBoxLayout()
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._refresh)
        clear_btn = QPushButton("Clear History")
        clear_btn.setStyleSheet("QPushButton { color: #ff6666; }")
        clear_btn.clicked.connect(self._confirm_clear)
        btn_row.addWidget(refresh_btn)
        btn_row.addWidget(clear_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        count_lbl = QLabel("")
        count_lbl.setStyleSheet("color: #666; font-size: 11px;")
        layout.addWidget(count_lbl)
        self._count_lbl = count_lbl

        self._refresh()

    @staticmethod
    def _transcript_path():
        return TRANSCRIPTS_PATH

    def _refresh(self):
        path = self._transcript_path()
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = [l.strip() for l in f if l.strip()]
        except FileNotFoundError:
            lines = []
        self._text.setPlainText("\n".join(lines) if lines else "(No transcripts yet)")
        self._count_lbl.setText(f"{len(lines)} entries  —  {path}")

    def _confirm_clear(self):
        reply = QMessageBox.question(
            self, "Clear Transcript History",
            "Delete all saved transcript entries?\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                open(self._transcript_path(), "w", encoding="utf-8").close()
            except Exception:
                pass
            self._refresh()


class HotkeysTab(QGroupBox):

    _ACTION_LABELS = {
        "pause": "Pause / Resume",
        "show_hide": "Show / Hide window",
        "copy": "Copy to clipboard",
        "toggle_minimal": "Toggle Minimal Mode",
    }
    _ACTION_ORDER = ["pause", "show_hide", "copy", "toggle_minimal"]

    def __init__(self, cfg, parent=None):
        super().__init__("Hotkeys", parent)
        layout = QFormLayout(self)

        hk = cfg.get("hotkeys", DEFAULT_CONFIG["hotkeys"])
        self._mod_combos = {}
        self._key_combos = {}

        for action in self._ACTION_ORDER:
            combo_str = hk.get(action, "")
            mod_val, key_str = self._parse_combo(combo_str)

            row_layout = QHBoxLayout()
            row_layout.setSpacing(6)

            mod_combo = QComboBox()
            for name, val in MODIFIER_COMBOS:
                mod_combo.addItem(name, val)
            idx = next((i for i, (_, v) in enumerate(MODIFIER_COMBOS) if v == mod_val), 0)
            mod_combo.setCurrentIndex(idx)
            mod_combo.setFixedWidth(100)
            row_layout.addWidget(mod_combo)
            self._mod_combos[action] = mod_combo

            key_combo = QComboBox()
            key_combo.setEditable(True)
            keys_list = [chr(c) for c in range(0x41, 0x5B)] + [str(i) for i in range(10)]
            keys_list += ["F1","F2","F3","F4","F5","F6","F7","F8","F9","F10","F11","F12"]
            for k in keys_list:
                key_combo.addItem(k)
            if key_str:
                k_idx = key_combo.findText(key_str)
                if k_idx >= 0:
                    key_combo.setCurrentIndex(k_idx)
                else:
                    key_combo.setCurrentText(key_str)
            key_combo.setFixedWidth(70)
            row_layout.addWidget(key_combo)
            self._key_combos[action] = key_combo

            row_layout.addStretch()
            layout.addRow(f"{self._ACTION_LABELS[action]}:", row_layout)

        info = QLabel("Hotkeys are global — they work even when the\n"
                       "app is in the background.")
        info.setStyleSheet("color: #888; font-size: 11px;")
        layout.addRow(info)

    @staticmethod
    def _parse_combo(combo_str):
        """Parse 'Ctrl+Shift+P' into (mod_int, key_str)."""
        parts = [p.strip() for p in combo_str.split("+")]
        mods = {"Ctrl": MOD_CTRL, "Shift": MOD_SHIFT, "Alt": MOD_ALT}
        mod_val = 0
        key_str = ""
        for p in parts:
            if p in mods:
                mod_val |= mods[p]
            elif p:
                key_str = p
        return mod_val, key_str

    def apply(self, cfg):
        if "hotkeys" not in cfg:
            cfg["hotkeys"] = {}
        for action in self._ACTION_ORDER:
            mod_val = self._mod_combos[action].currentData()
            key = self._key_combos[action].currentText().strip()
            mod_names = [name for name, val in MODIFIER_COMBOS if val == mod_val]
            mod_str = mod_names[0] if mod_names else ""
            combo_str = f"{mod_str}+{key}" if mod_str else key
            cfg["hotkeys"][action] = combo_str


# ---------------------------------------------------------------------------
# Main dialog
# ---------------------------------------------------------------------------

class SettingsDialog(QDialog):
    signal_config_changed = pyqtSignal()

    def __init__(self, parent=None, pipeline=None, translator=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumSize(520, 440)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        self._pipeline = pipeline
        self._translator = translator
        self._vu_worker = None
        self._cfg = load_config()

        self._tabs = QTabWidget()
        self._audio = AudioTab(self._cfg)
        self._asr = ASRTab(self._cfg)
        self._translate = TranslateTab(self._cfg)
        self._ui_tab = UITab(self._cfg)
        self._hotkeys = HotkeysTab(self._cfg)
        self._history = HistoryTab()

        self._tabs.addTab(self._audio, "Audio")
        self._tabs.addTab(self._asr, "ASR")
        self._tabs.addTab(self._translate, "Translate")
        self._tabs.addTab(self._ui_tab, "UI")
        self._tabs.addTab(self._hotkeys, "Hotkeys")
        self._tabs.addTab(self._history, "History")

        # Buttons
        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Apply
            | QDialogButtonBox.StandardButton.Cancel
        )
        btn_box.accepted.connect(self._on_ok)
        btn_box.rejected.connect(self.reject)
        apply_btn = btn_box.button(QDialogButtonBox.StandardButton.Apply)
        apply_btn.clicked.connect(self._on_apply)

        # Restore Defaults button
        restore_btn = QPushButton("Restore Defaults")
        restore_btn.clicked.connect(self._on_restore)

        btn_layout = QHBoxLayout()
        btn_layout.addWidget(restore_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(btn_box)

        main_layout = QVBoxLayout(self)
        main_layout.addWidget(self._tabs)
        main_layout.addLayout(btn_layout)

        self._start_vu_meter()

    def _start_vu_meter(self):
        if self._pipeline:
            self._vu_worker = VUMeterPollWorker()
            self._vu_worker.start(self._audio.vu_meter_widget, self._pipeline)

    def _stop_vu_meter(self):
        if self._vu_worker:
            self._vu_worker.stop()
            self._vu_worker = None

    def closeEvent(self, event):
        self._stop_vu_meter()
        super().closeEvent(event)

    def reject(self):
        self._stop_vu_meter()
        super().reject()

    def _gather(self):
        self._audio.apply(self._cfg)
        self._asr.apply(self._cfg)
        self._translate.apply(self._cfg)
        self._ui_tab.apply(self._cfg)
        self._hotkeys.apply(self._cfg)

    def _on_apply(self):
        self._gather()
        # Merge with defaults so new fields always exist
        merged = copy.deepcopy(DEFAULT_CONFIG)
        _deep_merge(merged, self._cfg)
        self._cfg = merged
        save_config(self._cfg)
        self.signal_config_changed.emit()

    def _on_ok(self):
        self._on_apply()
        self.accept()

    def _on_restore(self):
        reply = QMessageBox.question(
            self, "Restore Defaults",
            "Reset ALL settings to factory defaults?\n\n"
            "Your current settings will be lost.\n"
            "The application may need to restart.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        save_config(copy.deepcopy(DEFAULT_CONFIG))
        self._cfg = load_config()
        self.signal_config_changed.emit()
        self.accept()
