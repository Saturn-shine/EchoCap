# EchoCap

Real-time offline bilingual caption overlay for Windows. Live offline speech recognition + offline translation displayed as a transparent floating window. Built for streamers, presenters, and creators.

By [Saturn_shine](https://github.com/Saturn-shine)

---

## Download

Get the latest installer from **[GitHub Releases](https://github.com/Saturn-shine/EchoCap/releases)**.

The installer bundles everything — the app, ASR model (faster-whisper-small), and translation model (opus-mt-en-zh). No internet required after install. Just run and speak.

> Requires Windows 10+. NVIDIA GPU recommended for real-time performance (CPU fallback works but is slower).

---

## Features

- **Real-time ASR** — Speech-to-text via [faster-whisper](https://github.com/SYSTRAN/faster-whisper) with GPU acceleration (ctranslate2 + CUDA)
- **Real-time Translation** — English → Chinese via MarianMT ([Helsinki-NLP/opus-mt-en-zh](https://huggingface.co/Helsinki-NLP/opus-mt-en-zh))
- **Transparent Overlay** — Always-on-top, frameless, draggable, resizable window
- **Global Hotkeys** — Configurable shortcuts that work while other apps are focused
- **5 Color Themes** — Dark Gold, Pure White, Cyber Green, Warm Orange, Nord Blue
- **OBS Chroma Key** — Green/blue screen background modes for streaming
- **System Tray** — Pause, resume, show/hide, click-through, settings, export
- **Transcript Export** — Save captions as `.srt` (SubRip) for video editing
- **Minimal Mode** — Compact single-line overlay
- **Auto-Start** — Optional launch on Windows boot

---

## Usage

1. Launch EchoCap from the desktop shortcut or start menu
2. Speak into your default microphone — captions appear at the bottom of the screen
3. Hover over the overlay to reveal the toolbar (opacity, font size, OBS mode, theme, etc.)
4. Right-click the tray icon for pause/resume, click-through, export, settings
5. Double-click the tray icon to show/hide the overlay

### Key Bindings

| Shortcut | Action |
|---|---|
| `Ctrl+Shift+P` | Pause / Resume |
| `Ctrl+Shift+H` | Show / Hide window |
| `Ctrl+Shift+C` | Copy current caption to clipboard |
| `Ctrl+Shift+T` | Toggle Chinese translation |

All hotkeys can be changed in **Settings → Hotkeys**.

### OBS Setup

1. Add a **Window Capture** source → set window to `[EchoCap]`
2. In EchoCap, click the **🎬** toolbar button to enable green screen mode
3. In OBS, add a **Chroma Key** filter on the Window Capture source
4. Set key color to match (green: `#00FF00`, blue: `#0000FF`)

---

## Run from Source

```bash
git clone https://github.com/Saturn-shine/EchoCap.git
cd EchoCap
pip install -r requirements.txt
python main.py
```

On first run, Whisper and translation models download automatically from HuggingFace (~1.5 GB). If HuggingFace is unreliable in your region, set the HF mirror in Settings or place models manually.

### Build the Installer

```bash
# Prerequisites: PyInstaller, Inno Setup 6
# 1. Build the exe
pyinstaller --clean EchoCap.spec
# 2. Prepare model files (trims unused files)
python prepare_models.py
# 3. Build the Windows installer
iscc installer.iss
# Output: Output/EchoCap_Setup.exe
```

Or run `build_exe.bat` to do all steps at once.

---

## Project Structure

```
EchoCap/
  main.py              # App entry point and orchestration
  overlay.py           # Transparent overlay window (PyQt6)
  pipeline.py          # Streaming ASR + translation loop
  asr_engine.py        # faster-whisper wrapper
  translator.py        # MarianMT translation wrapper
  hotkeys.py           # Global Windows hotkeys (RegisterHotKey)
  settings_dialog.py   # Settings dialog (5 tabs)
  tray_icon.py         # System tray icon and menu
  app_icon.py          # Programmatic microphone icon
  about_dialog.py      # About dialog with credits
  export_srt.py        # Transcript → SubRip converter
  update_checker.py    # GitHub release checker
  config.py            # Config I/O and defaults
  paths.py             # Cross-platform path resolution
  logging_config.py    # Logging configuration
  prepare_models.py    # Model file trimmer (for installer)
  hooks/               # PyInstaller custom hooks
  build_exe.bat        # Full build pipeline script
  installer.iss        # Inno Setup installer script
  requirements.txt     # Python dependencies
  VERSION              # Version file
```

---

## Models & Licenses

| Model | License | Source |
|---|---|---|
| faster-whisper-small (Systran) | MIT | Based on OpenAI Whisper |
| opus-mt-en-zh (Helsinki-NLP) | [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/) | HuggingFace |

EchoCap itself is licensed under **MIT**.

---

## Settings Reference

| Tab | Options |
|---|---|
| **Audio** | Input device, sample rate, VAD sensitivity, silence timeout |
| **ASR** | Model path, device (auto/CUDA/CPU), compute type, HF endpoint |
| **Translate** | Language pair, local model path |
| **UI** | Font sizes, colors, opacity, fade-out, font family, alignment, click-through |
| **Hotkeys** | All four global shortcuts — fully configurable |
