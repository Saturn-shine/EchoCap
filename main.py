"""
EchoCap — Real-time Bilingual Caption Overlay
----------------------------------------------
Live streaming pipeline:
  Mic -> VAD -> incremental ASR (faster-whisper) -> MarianMT translation -> overlay.

Usage:
    python main.py
"""

import logging
import os
import queue
import sys
import threading
import traceback as _traceback

# ------------------------------------------------------------------
# CUDA / GPU setup — must run BEFORE any model imports
# ------------------------------------------------------------------
def _setup_cuda_dll_paths():
    """Pre-load NVIDIA GPU libraries so ctranslate2 and PyTorch can use CUDA."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        import site
        site_packages = site.getsitepackages()
    except Exception:
        return
    try:
        site_packages.append(site.getusersitepackages())
    except Exception:
        pass
    for sp in site_packages:
        for sub in ["nvidia/cuda_runtime/bin", "nvidia/cublas/bin"]:
            d = os.path.join(sp, sub)
            if os.path.isdir(d):
                try:
                    os.add_dll_directory(d)
                except Exception:
                    pass

_setup_cuda_dll_paths()

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QMessageBox

from asr_engine import ASREngine
from translator import Translator
from overlay import OverlayWindow
from tray_icon import SystemTray
from pipeline import StreamingPipeline
from hotkeys import GlobalHotkeys
from settings_dialog import SettingsDialog
from app_icon import get_app_icon
from about_dialog import AboutDialog
from export_srt import export_srt
from update_checker import check_for_updates
from paths import BASE_DIR, CONFIG_PATH, TRANSCRIPTS_PATH, VERSION_PATH
from config import load_config, save_config, save_ui_key

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Global exception hook
# ------------------------------------------------------------------

def _global_exception_hook(exc_type, exc_value, exc_tb):
    """Catch unhandled exceptions in the Qt event loop and show a dialog."""
    tb_str = "".join(_traceback.format_exception(exc_type, exc_value, exc_tb))
    logger.critical("Unhandled exception:\n%s", tb_str)

    try:
        if QApplication.instance():
            msg = QMessageBox()
            msg.setIcon(QMessageBox.Icon.Critical)
            msg.setWindowTitle("EchoCap - Unexpected Error")
            msg.setText("An unexpected error occurred.")
            msg.setInformativeText(
                f"{exc_type.__name__}: {exc_value}\n\n"
                "The application will try to continue.\n"
                "Please report this issue on GitHub."
            )
            msg.setDetailedText(tb_str)
            msg.setStandardButtons(QMessageBox.StandardButton.Ok)
            copy_btn = msg.addButton("Copy to Clipboard",
                                      QMessageBox.ButtonRole.ActionRole)
            copy_btn.clicked.connect(lambda: QApplication.clipboard().setText(tb_str))
            msg.exec()
    except Exception:
        pass


def _thread_exception_hook(args):
    """Catch unhandled exceptions in non-Qt threads."""
    _global_exception_hook(args.exc_type, args.exc_value, args.exc_traceback)


sys.excepthook = _global_exception_hook
threading.excepthook = _thread_exception_hook


# ------------------------------------------------------------------
# Auto-start with Windows
# ------------------------------------------------------------------

def _apply_auto_start(enable):
    """Create or remove registry Run key for auto-start."""
    import winreg
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    app_name = "EchoCap"
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0,
                             winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE)
    except OSError:
        return

    try:
        if enable:
            exe_path = sys.executable
            script = os.path.join(BASE_DIR, "main.py")
            winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ,
                              f'"{exe_path}" "{script}"')
            logger.info("Auto-start enabled.")
        else:
            try:
                winreg.DeleteValue(key, app_name)
                logger.info("Auto-start disabled.")
            except FileNotFoundError:
                pass
    finally:
        winreg.CloseKey(key)


# ------------------------------------------------------------------
# App
# ------------------------------------------------------------------

class App:
    def __init__(self):
        self.cfg = load_config()

        # In frozen mode, auto-detect models bundled next to the exe.
        self._auto_detect_models()

        # Qt application (must be first)
        self.app = QApplication(sys.argv)
        self.app.setWindowIcon(get_app_icon())
        self.app.setQuitOnLastWindowClosed(False)

        # HF mirror for model downloads
        if self.cfg["asr"].get("hf_endpoint"):
            os.environ["HF_ENDPOINT"] = self.cfg["asr"]["hf_endpoint"]

        # --- Init UI ---
        self.window = OverlayWindow()
        self.window.show()
        self.window.center_on_screen()

        self.tray = SystemTray()
        self.tray.show()

        # Text queue: pipeline -> overlay (thread-safe, polled by QTimer)
        self._text_queue = queue.Queue()
        self.window.set_text_queue(self._text_queue)

        # Wire tray -> app
        self.tray.signal_pause.connect(self._on_pause)
        self.tray.signal_show_window.connect(self._show_window)
        self.tray.signal_exit.connect(self._quit)
        self.tray.signal_settings.connect(self._show_settings)
        self.tray.signal_toggle_click_through.connect(self._set_click_through)
        self.tray.signal_about.connect(self._show_about)
        self.tray.signal_export.connect(self._export_transcript)

        # Wire overlay -> app
        self.window.signal_pause.connect(self._on_pause)

        # --- Global hotkeys ---
        self.hotkeys = GlobalHotkeys()
        hwnd = int(self.window.winId())
        self.hotkeys.register(hwnd)

        self.hotkeys.signal_pause.connect(lambda: self._on_pause(not self._paused))
        self.hotkeys.signal_show_hide.connect(self._toggle_window_visibility)
        self.hotkeys.signal_copy.connect(self._copy_current_text)
        self.hotkeys.signal_toggle_minimal.connect(self._toggle_minimal_mode)

        # --- Settings dialog ---
        self._settings_dialog = None
        self.window.signal_open_settings.connect(self._show_settings)

        self._paused = False
        self.tray.set_click_through(self.cfg["ui"].get("click_through", False))

        # --- Load ASR model ---
        self.window.show_text("Loading ASR model...", "")
        QApplication.processEvents()

        asr_cfg = self.cfg["asr"]
        self.asr = ASREngine(
            model_size=asr_cfg["model_size"],
            device=asr_cfg["device"],
            compute_type=asr_cfg["compute_type"],
        )
        self.asr.load()

        # --- Load translator ---
        self.window.show_text("Loading translator...", "")
        QApplication.processEvents()

        tr_cfg = self.cfg["translate"]
        self.translator = Translator(
            source=tr_cfg["source"],
            target=tr_cfg["target"],
            model_path=tr_cfg.get("model_path"),
        )
        self.translator.load()

        # Clear loading message
        self.window.show_text("", "")
        self.window._start_fade_out()

        # --- Start streaming pipeline ---
        audio_cfg = self.cfg["audio"]
        self.pipeline = StreamingPipeline(
            self.asr, self.translator, self.window,
            sample_rate=audio_cfg["sample_rate"],
            chunk_ms=audio_cfg["chunk_duration_ms"],
            vad_mode=audio_cfg["vad_mode"],
            process_interval_s=audio_cfg.get("process_interval_s", 0.4),
            silence_timeout_s=audio_cfg.get("silence_timeout_s", 0.7),
            max_segment_s=audio_cfg.get("max_segment_s", 4.0),
            min_speech_s=audio_cfg.get("min_speech_s", 0.5),
            device=audio_cfg.get("device"),
            text_queue=self._text_queue,
        )

        # Apply auto-start on initial launch
        _apply_auto_start(self.cfg["ui"].get("auto_start", False))

    @staticmethod
    def _find_models_dir():
        """Return the bundled models directory, or None if not found."""
        if not getattr(sys, 'frozen', False):
            return None
        candidate = os.path.join(os.path.dirname(sys.executable), "models")
        return candidate if os.path.isdir(candidate) else None

    @staticmethod
    def _is_valid_asr_dir(path):
        """Check that *path* actually contains a faster-whisper model file."""
        return bool(path) and os.path.isdir(path) and os.path.isfile(os.path.join(path, "model.bin"))

    @staticmethod
    def _is_valid_translator_dir(path):
        """Check that *path* actually contains a MarianMT model file."""
        return bool(path) and os.path.isdir(path) and (
            os.path.isfile(os.path.join(path, "pytorch_model.bin"))
            or os.path.isfile(os.path.join(path, "model.safetensors"))
        )

    def _auto_detect_models(self):
        """Auto-detect models bundled in the install directory next to the exe.

        Only kicks in when config doesn't already point to a directory that
        actually contains the expected model files (not just any directory).
        Updates self.cfg in-place and persists to config.json.
        """
        models_dir = self._find_models_dir()
        if not models_dir:
            return

        changed = False
        asr_path = self.cfg["asr"].get("model_size", "")
        asr_default = os.path.join(models_dir, "whisper-small")
        if not self._is_valid_asr_dir(asr_path) and self._is_valid_asr_dir(asr_default):
            logger.info("Auto-detected ASR model: %s", asr_default)
            self.cfg["asr"]["model_size"] = asr_default
            changed = True

        tr_path = self.cfg["translate"].get("model_path", "")
        tr_default = os.path.join(models_dir, "opus-mt-en-zh")
        if not self._is_valid_translator_dir(tr_path) and self._is_valid_translator_dir(tr_default):
            logger.info("Auto-detected translation model: %s", tr_default)
            self.cfg["translate"]["model_path"] = tr_default
            changed = True

        if changed:
            save_config(self.cfg)

    def start(self):
        self.pipeline.start()
        logger.info("Ready. Speak into your microphone.")
        # Background update check after 5s
        QTimer.singleShot(5000, lambda: check_for_updates(
            on_result=lambda ver: self._on_update_available(ver)))
        self.app.exec()

    @staticmethod
    def _on_update_available(remote_ver):
        try:
            with open(VERSION_PATH, "r", encoding="utf-8") as f:
                local = f.read().strip()
        except Exception:
            local = "1.0.0"
        QMessageBox.information(
            None, "Update Available",
            f"A new version is available!\n\n"
            f"Current: {local}\n"
            f"Latest:  {remote_ver}\n\n"
            f"Visit GitHub to download.")

    def _quit(self):
        if hasattr(self, 'pipeline'):
            self.pipeline.stop()
        if hasattr(self, 'hotkeys'):
            self.hotkeys.unregister()
        self.app.quit()

    def _show_about(self):
        dlg = AboutDialog()
        dlg.exec()

    def _export_transcript(self):
        from PyQt6.QtWidgets import QFileDialog

        transcripts_path = TRANSCRIPTS_PATH
        if not os.path.exists(transcripts_path):
            QMessageBox.information(
                None, "Export Transcript",
                "No transcript file found yet.\n"
                "Transcripts are saved when captions appear.")
            return

        path, _ = QFileDialog.getSaveFileName(
            None, "Export Transcript as SRT",
            os.path.join(os.path.expanduser("~"), "Desktop", "captions.srt"),
            "SubRip Subtitles (*.srt);;All Files (*.*)")
        if not path:
            return

        try:
            count = export_srt(transcripts_path, path)
            QMessageBox.information(
                None, "Export Complete",
                f"Exported {count} caption entries to:\n{path}")
        except Exception as e:
            logger.error("Export failed: %s", e, exc_info=True)
            QMessageBox.critical(
                None, "Export Failed",
                f"Could not export transcript:\n{e}")

    def _on_pause(self, paused):
        self._paused = paused
        if hasattr(self, 'pipeline'):
            self.pipeline.set_paused(paused)
        logger.info("%s", "Paused" if paused else "Resumed")

    def _show_window(self):
        self.window.show()
        self.window.raise_()
        self.window._fade_in()

    def _toggle_window_visibility(self):
        if self.window.isVisible():
            self.window.hide()
        else:
            self.window.show()
            self.window.raise_()
            self.window._fade_in()

    def _copy_current_text(self):
        en = self.window._current_en
        zh = self.window._current_zh or self.window._caption_line.label_zh.text()
        text = f"{en}\n{zh}" if zh else en
        if text.strip():
            QApplication.clipboard().setText(text.strip())

    def _toggle_minimal_mode(self):
        enabled = not self.window._minimal_mode
        self.window._set_minimal(enabled)

    def _set_click_through(self, enabled):
        self.window._click_through = enabled
        self.window._apply_click_through(enabled)
        save_ui_key("click_through", enabled)
        logger.info("Click-through: %s", "ON" if enabled else "OFF")

    def _show_settings(self):
        if self._settings_dialog is not None:
            self._settings_dialog.signal_config_changed.disconnect(self._on_config_changed)
            self._settings_dialog.deleteLater()
            self._settings_dialog = None
        self._settings_dialog = SettingsDialog(
            pipeline=self.pipeline if hasattr(self, 'pipeline') else None,
            translator=self.translator if hasattr(self, 'translator') else None,
        )
        self._settings_dialog.signal_config_changed.connect(self._on_config_changed)
        self._settings_dialog.show()
        self._settings_dialog.raise_()
        self._settings_dialog.activateWindow()

    def _on_config_changed(self):
        self.cfg = load_config()
        ui = self.cfg["ui"]
        self.window._ui = ui
        self.window._show_zh = ui.get("show_zh", True)
        self.window._obs_mode = ui.get("obs_mode", "off")
        self.window._cur_theme = ui.get("theme", "Dark Gold")
        self.window._update_obs_button()
        self.window._apply_theme()
        self.window._caption_line.set_font_size_en(ui.get("font_size_en", 26))
        self.window._caption_line.set_font_size_zh(ui.get("font_size_zh", 20))
        self.window._caption_line.set_alignment(ui.get("text_align", "left"))
        self.window._apply_click_through(ui.get("click_through", False))
        self.window._minimal_mode = ui.get("minimal_mode", False)
        self.window._set_minimal(self.window._minimal_mode)
        _apply_auto_start(ui.get("auto_start", False))
        self.window._click_through = ui.get("click_through", False)
        self.window._opacity_slider.blockSignals(True)
        self.window._opacity_slider.setValue(int(ui.get("bg_opacity", 0.55) * 100))
        self.window._opacity_slider.blockSignals(False)
        self.window.repaint()
        if hasattr(self, 'hotkeys'):
            self.hotkeys.reregister()
        self.tray.set_click_through(ui.get("click_through", False))
        logger.info("Config reloaded from settings.")


def main():
    from logging_config import setup_logging
    setup_logging()
    logger.info("EchoCap starting...")

    app = App()
    try:
        app.start()
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt, exiting.")
    except Exception as e:
        logger.critical("Fatal error: %s", e, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
