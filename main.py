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
    """Pre-load NVIDIA GPU libraries so ctranslate2 can use CUDA."""
    if sys.platform != "win32":
        return
    nvidia_dirs = []
    # 1. Bundled DLLs inside frozen app (onedir: _internal/ next to exe)
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
        nvidia_dirs.append(exe_dir)
        nvidia_dirs.append(os.path.join(exe_dir, '_internal'))
    # 2. pip-installed nvidia packages (dev mode)
    try:
        import site
        for sp in site.getsitepackages():
            nvidia_dirs.append(sp)
        nvidia_dirs.append(site.getusersitepackages())
    except Exception:
        pass
    # 3. Common CUDA install paths
    for p in [os.environ.get("CUDA_PATH", ""),
              r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA"]:
        if p and os.path.isdir(p):
            nvidia_dirs.append(p)
    found_dlls = []
    for sp in nvidia_dirs:
        for sub in ["nvidia/cublas/bin", "nvidia/cuda_runtime/bin", "bin"]:
            d = os.path.join(sp, sub)
            if os.path.isdir(d):
                try:
                    os.add_dll_directory(d)
                except Exception:
                    pass
                for fn in sorted(os.listdir(d)):
                    if fn.endswith('.dll'):
                        found_dlls.append(os.path.join(d, fn))
    # Pre-load DLLs explicitly — ensures they're in process memory
    # before ctranslate2 tries to lazy-load them.
    try:
        import ctypes
        for dll_path in found_dlls:
            try:
                ctypes.CDLL(dll_path)
            except Exception:
                pass
    except Exception:
        pass

_setup_cuda_dll_paths()

from PyQt6.QtCore import Qt, QTimer
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

        # History queue: pipeline -> history panel
        self._history_queue = queue.Queue()
        if hasattr(self.window, 'set_history_queue'):
            self.window.set_history_queue(self._history_queue)

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

        # --- Check models BEFORE attempting to load ---
        asr_ok, tr_ok = self._check_models()
        if asr_ok and tr_ok:
            self._load_models_and_start()
        else:
            self.window.show_text(
                "Models not found.\nClick the overlay or tray icon to set up models.", "")
            # Model setup wizard will be shown via tray/settings
            self.asr = None
            self.translator = None
            QTimer.singleShot(300, self._show_model_setup_wizard)

        # Apply auto-start on initial launch
        _apply_auto_start(self.cfg["ui"].get("auto_start", False))

    # ------------------------------------------------------------------
    # Model checking & setup wizard
    # ------------------------------------------------------------------

    def _check_models(self):
        """Return (asr_ok, translator_ok) — True if model files exist locally."""
        # 1. Check ASR model
        asr_path = self.cfg["asr"].get("model_size", "")
        asr_dirs = [asr_path] if asr_path else []
        default_asr = os.path.join(BASE_DIR, "dist", "models", "whisper-small")
        asr_dirs.append(default_asr)
        asr_ok = False
        for d in asr_dirs:
            if d and os.path.isdir(d) and os.path.isfile(os.path.join(d, "model.bin")):
                self.cfg["asr"]["model_size"] = d
                asr_ok = True
                break

        # 2. Check translation model
        tr_path = self.cfg["translate"].get("model_path", "")
        tr_ok = False
        # Try: model_path itself, model_path/opus-mt-en-zh, dist/models, dist/models/opus-mt-en-zh
        for candidate in self._get_translator_search_paths(tr_path):
            if os.path.isdir(candidate) and (
                os.path.isfile(os.path.join(candidate, "pytorch_model.bin")) or
                os.path.isfile(os.path.join(candidate, "model.safetensors"))
            ):
                self.cfg["translate"]["model_path"] = candidate
                tr_ok = True
                break

        if asr_ok and tr_ok:
            save_config(self.cfg)
        return asr_ok, tr_ok

    def _get_translator_search_paths(self, tr_path):
        """Generate candidate directories to search for the translation model."""
        paths = []
        if tr_path:
            paths.append(tr_path)
            paths.append(os.path.join(tr_path, "opus-mt-en-zh"))
        paths.append(os.path.join(BASE_DIR, "dist", "models", "opus-mt-en-zh"))
        paths.append(os.path.join(BASE_DIR, "dist", "models"))
        return paths

    def _load_models_and_start(self):
        """Load ASR + translator models and start the streaming pipeline."""
        asr_cfg = self.cfg["asr"]
        self.window.show_text("Loading ASR model...", "")
        QApplication.processEvents()
        self.asr = ASREngine(
            model_size=asr_cfg["model_size"],
            device=asr_cfg["device"],
            compute_type=asr_cfg["compute_type"],
        )
        self.asr.load()

        tr_cfg = self.cfg["translate"]
        self.window.show_text("Loading translator...", "")
        QApplication.processEvents()
        self.translator = Translator(
            source=tr_cfg["source"],
            target=tr_cfg["target"],
            model_path=tr_cfg.get("model_path"),
        )
        self.translator.load()

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
        # Show "Ready!" for 5 seconds
        self.window.show_text("Ready!", "")
        QTimer.singleShot(5000, lambda: self.window._start_fade_out())

    def _show_model_setup_wizard(self):
        """Show a proper dialog to download or locate model files."""
        from PyQt6.QtCore import QThread, pyqtSignal as _pyqtSignal
        from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                                      QPushButton, QLineEdit, QProgressBar,
                                      QFileDialog, QMessageBox)

        dlg = QDialog(self.window)
        dlg.setWindowTitle("EchoCap Model Setup")
        dlg.setMinimumWidth(520)
        layout = QVBoxLayout(dlg)
        layout.setSpacing(10)

        # --- Info ---
        layout.addWidget(QLabel(
            "EchoCap needs two AI models (~800 MB total):\n"
            "  • faster-whisper-small  (speech, ~487 MB)\n"
            "  • opus-mt-en-zh         (translation, ~312 MB)\n\n"
            "They download once, then work offline forever."))

        # --- Download folder row ---
        dl_row = QHBoxLayout()
        dl_row.addWidget(QLabel("Save to:"))
        default_dir = os.path.join(
            os.environ.get("APPDATA", os.path.expanduser("~")), "EchoCap", "models")
        dl_edit = QLineEdit(default_dir)
        dl_edit.setMinimumWidth(280)
        dl_row.addWidget(dl_edit)
        browse_btn = QPushButton("...")
        browse_btn.setFixedWidth(30)
        def _pick_dir():
            d = QFileDialog.getExistingDirectory(dlg, "Select download folder")
            if d: dl_edit.setText(d)
        browse_btn.clicked.connect(_pick_dir)
        dl_row.addWidget(browse_btn)
        layout.addLayout(dl_row)

        # --- Progress ---
        progress = QProgressBar()
        progress.setVisible(False)
        layout.addWidget(progress)
        status_lbl = QLabel("")
        status_lbl.setWordWrap(True)
        layout.addWidget(status_lbl)

        # --- Buttons ---
        btn_row = QHBoxLayout()
        btn_dl = QPushButton("Download Models")
        btn_local = QPushButton("Browse Local Files")
        btn_quit = QPushButton("Quit")
        btn_row.addWidget(btn_dl)
        btn_row.addWidget(btn_local)
        btn_row.addWidget(btn_quit)
        layout.addLayout(btn_row)

        # Tip + manual download links
        tip = QLabel("Tip: If auto-download fails, download models manually and use \"Browse Local Files\".")
        tip.setStyleSheet("color: #888; font-size: 10px;")
        layout.addWidget(tip)
        links = QLabel(
            '● <a href="https://hf-mirror.com/Systran/faster-whisper-small">'
            'faster-whisper-small</a> (China mainland mirror) &nbsp;|&nbsp; '
            '<a href="https://huggingface.co/Systran/faster-whisper-small">'
            'faster-whisper-small</a> (official)<br>'
            '● <a href="https://hf-mirror.com/Helsinki-NLP/opus-mt-en-zh">'
            'opus-mt-en-zh</a> (China mainland mirror) &nbsp;|&nbsp; '
            '<a href="https://huggingface.co/Helsinki-NLP/opus-mt-en-zh">'
            'opus-mt-en-zh</a> (official)'
        )
        links.setOpenExternalLinks(True)
        links.setStyleSheet("color: #888; font-size: 10px;")
        layout.addWidget(links)

        # --- Download worker thread ---
        class _DownloadWorker(QThread):
            progress_signal = _pyqtSignal(int, str)  # percent, status text
            finished_signal = _pyqtSignal(bool, str)  # success, message

            def __init__(self, target_dir):
                super().__init__()
                self.target_dir = target_dir

            def run(self):
                import urllib.request as _req, traceback
                os.makedirs(self.target_dir, exist_ok=True)

                # ModelScope CDN — direct URLs, no library dependency.
                # Works reliably in both dev and frozen (PyInstaller) modes.
                MS_CDN = "https://www.modelscope.cn/models/{repo}/resolve/master/{file}"
                whisper_files = {
                    "Systran/faster-whisper-small": [
                        "model.bin", "config.json", "tokenizer.json", "vocabulary.txt"
                    ],
                    "Helsinki-NLP/opus-mt-en-zh": [
                        "pytorch_model.bin", "config.json", "tokenizer_config.json",
                        "vocab.json", "source.spm", "target.spm", "generation_config.json",
                    ],
                }
                target_subdirs = {
                    "Systran/faster-whisper-small": "whisper-small",
                    "Helsinki-NLP/opus-mt-en-zh": "opus-mt-en-zh",
                }
                all_files = []
                for repo, files in whisper_files.items():
                    sub = target_subdirs[repo]
                    for fn in files:
                        all_files.append((repo, fn, os.path.join(self.target_dir, sub, fn)))

                fail = []
                total = len(all_files)
                for i, (repo, fn, dest) in enumerate(all_files):
                    pct = int(5 + (i / total) * 90)
                    self.progress_signal.emit(pct, f"Downloading {repo.split('/')[-1]}/{fn}...")
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    url = MS_CDN.format(repo=repo, file=fn)
                    try:
                        _req.urlretrieve(url, dest)
                    except Exception as e:
                        fail.append(f"{repo}/{fn}: {e}")

                if fail:
                    self.finished_signal.emit(False,
                        f"Download failed for {len(fail)}/{total} files:\n"
                        + "\n".join(fail[:5]) + "\n\n"
                        "Please download models manually:\n\n"
                        "ASR: faster-whisper-small (~487 MB)\n"
                        "  https://hf-mirror.com/Systran/faster-whisper-small  (China mainland mirror)\n"
                        "  https://huggingface.co/Systran/faster-whisper-small  (official)\n\n"
                        "Translation: opus-mt-en-zh (~312 MB)\n"
                        "  https://hf-mirror.com/Helsinki-NLP/opus-mt-en-zh  (China mainland mirror)\n"
                        "  https://huggingface.co/Helsinki-NLP/opus-mt-en-zh  (official)")
                    return
                self.progress_signal.emit(100, "All models downloaded successfully!")
                self.finished_signal.emit(True, "")

        worker = None
        timeout_timer = None
        fake_progress_timer = None

        def _start_fake_progress():
            """Smooth fake progress ~1 min. ASR 30s (5→45%), pause, TL 25s (50→95%), final ~3s (95→99%)."""
            nonlocal fake_progress_timer
            elapsed = 0
            def _tick():
                nonlocal elapsed
                elapsed += 0.1
                if elapsed < 30:
                    pct = int(5 + (elapsed / 30) * 40)  # 5% → 45%
                    status_lbl.setText(f"Downloading whisper-small (~487 MB)... ({int(elapsed)}s)")
                elif elapsed < 33:
                    pct = 45
                    status_lbl.setText("whisper-small downloaded. Preparing translation model...")
                elif elapsed < 58:
                    pct = int(50 + ((elapsed - 33) / 25) * 45)  # 50% → 95%
                    status_lbl.setText(f"Downloading opus-mt-en-zh (~312 MB)... ({int(elapsed - 33)}s)")
                elif elapsed < 60:
                    pct = int(95 + ((elapsed - 58) / 2) * 4)  # 95% → 99%
                    status_lbl.setText("Finalizing...")
                else:
                    # Hold at 99% — wait for real download to finish
                    fake_progress_timer.stop()
                    return
                progress.setValue(min(pct, 99))
            fake_progress_timer = QTimer(dlg)
            fake_progress_timer.timeout.connect(_tick)
            fake_progress_timer.start(100)

        def _stop_fake_progress(pct, msg):
            nonlocal fake_progress_timer
            if fake_progress_timer:
                fake_progress_timer.stop()
                fake_progress_timer = None
            progress.setValue(pct)
            status_lbl.setText(msg)

        def _do_download():
            nonlocal worker, timeout_timer
            target = dl_edit.text().strip()
            if not target:
                QMessageBox.warning(dlg, "Error", "Please choose a download folder.")
                return
            os.makedirs(target, exist_ok=True)

            # Save config
            self.cfg["asr"]["model_size"] = os.path.join(target, "whisper-small")
            self.cfg["translate"]["model_path"] = target
            save_config(self.cfg)

            # Start download in background + fake progress animation
            btn_dl.setEnabled(False)
            btn_local.setEnabled(False)
            progress.setVisible(True)
            _start_fake_progress()
            worker = _DownloadWorker(target)
            worker.finished_signal.connect(lambda ok, msg: _on_dl_done(ok, msg))
            worker.start()

            # Auto-timeout after 10 minutes
            def _on_timeout():
                if worker and worker.isRunning():
                    worker.terminate()
                    worker.wait()
                    _on_dl_done(False,
                    "Download timed out after 10 minutes.\n\n"
                    "Please download models manually:\n\n"
                    "ASR: faster-whisper-small (~487 MB)\n"
                    "  https://hf-mirror.com/Systran/faster-whisper-small  (China mainland mirror)\n"
                    "  https://huggingface.co/Systran/faster-whisper-small  (official)\n\n"
                    "Translation: opus-mt-en-zh (~312 MB)\n"
                    "  https://hf-mirror.com/Helsinki-NLP/opus-mt-en-zh  (China mainland mirror)\n"
                    "  https://huggingface.co/Helsinki-NLP/opus-mt-en-zh  (official)")
            timeout_timer = QTimer(dlg)
            timeout_timer.setSingleShot(True)
            timeout_timer.timeout.connect(_on_timeout)
            timeout_timer.start(600000)  # 10 minutes

        def _on_dl_done(success, message):
            nonlocal timeout_timer, fake_progress_timer
            if timeout_timer:
                timeout_timer.stop()
            if fake_progress_timer:
                fake_progress_timer.stop()
            progress.setValue(100 if success else 0)
            btn_dl.setEnabled(True)
            btn_local.setEnabled(True)
            if success:
                dlg.accept()
                self._restart_app()
            else:
                progress.setVisible(False)
                err_msg = QMessageBox(dlg)
                err_msg.setWindowTitle("Download Failed")
                err_msg.setIcon(QMessageBox.Icon.Warning)
                err_msg.setTextFormat(Qt.TextFormat.RichText)
                # Convert plain URLs to clickable HTML links
                html = message.replace("\n", "<br>")
                html = html.replace(
                    "https://hf-mirror.com/Systran/faster-whisper-small",
                    '<a href="https://hf-mirror.com/Systran/faster-whisper-small">https://hf-mirror.com/Systran/faster-whisper-small</a>')
                html = html.replace(
                    "https://huggingface.co/Systran/faster-whisper-small",
                    '<a href="https://huggingface.co/Systran/faster-whisper-small">https://huggingface.co/Systran/faster-whisper-small</a>')
                html = html.replace(
                    "https://hf-mirror.com/Helsinki-NLP/opus-mt-en-zh",
                    '<a href="https://hf-mirror.com/Helsinki-NLP/opus-mt-en-zh">https://hf-mirror.com/Helsinki-NLP/opus-mt-en-zh</a>')
                html = html.replace(
                    "https://huggingface.co/Helsinki-NLP/opus-mt-en-zh",
                    '<a href="https://huggingface.co/Helsinki-NLP/opus-mt-en-zh">https://huggingface.co/Helsinki-NLP/opus-mt-en-zh</a>')
                err_msg.setText(html)
                err_msg.exec()

        def _do_browse():
            path = QFileDialog.getExistingDirectory(dlg, "Select folder containing model files")
            if not path:
                return
            # Try to find whisper-small: in path itself or path/whisper-small
            wp = path if os.path.isfile(os.path.join(path, "model.bin")) else os.path.join(path, "whisper-small")
            w_ok = os.path.isdir(wp) and os.path.isfile(os.path.join(wp, "model.bin"))
            # Try to find opus-mt-en-zh: in path, path/opus-mt-en-zh, or path itself as parent
            op_candidates = [
                os.path.join(path, "opus-mt-en-zh"),
                path,
                os.path.join(path, "opus-mt-en-zh-ct2"),
            ]
            op = None
            for c in op_candidates:
                if os.path.isdir(c) and (
                    os.path.isfile(os.path.join(c, "pytorch_model.bin")) or
                    os.path.isfile(os.path.join(c, "model.safetensors")) or
                    os.path.isfile(os.path.join(c, "model.bin"))
                ):
                    op = c
                    break
            o_ok = op is not None
            if w_ok and o_ok:
                self.cfg["asr"]["model_size"] = wp
                self.cfg["translate"]["model_path"] = op
                save_config(self.cfg)
                dlg.accept()
                QTimer.singleShot(300, self._restart_app)
            else:
                missing = []
                if not w_ok: missing.append("whisper-small/  (with model.bin)")
                if not o_ok: missing.append("opus-mt-en-zh/  (with pytorch_model.bin)")
                QMessageBox.warning(dlg, "Not Found",
                    f"Could not find model files in:\n{path}\n\n"
                    "Missing:\n  " + "\n  ".join(missing))

        btn_dl.clicked.connect(_do_download)
        btn_local.clicked.connect(_do_browse)
        btn_quit.clicked.connect(dlg.reject)

        dlg.exec()

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
        if hasattr(self, 'pipeline') and self.pipeline is not None:
            self.pipeline.start()
            logger.info("Ready. Speak into your microphone.")
        else:
            logger.info("Models not loaded — pipeline not started.")
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
        if hasattr(self, 'pipeline') and self.pipeline is not None:
            self.pipeline.stop()
        if hasattr(self, 'hotkeys'):
            self.hotkeys.unregister()
        self.app.quit()

    def _restart_app(self):
        """Quit and relaunch EchoCap (no terminal window)."""
        if getattr(sys, 'frozen', False):
            os.startfile(sys.executable)
        else:
            import subprocess
            python = sys.executable
            script = os.path.join(BASE_DIR, "main.py")
            # CREATE_NO_WINDOW flag to suppress terminal popup
            subprocess.Popen(
                [python, script],
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0,
            )
        self._quit()

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
