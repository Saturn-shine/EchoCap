"""
Centralised configuration management.

All config I/O lives here. Other modules import the functions they need
rather than each implementing their own file access.
"""

import copy
import json
import logging

from paths import CONFIG_PATH

logger = logging.getLogger(__name__)

DEFAULT_CONFIG = {
    "audio": {
        "sample_rate": 16000,
        "chunk_duration_ms": 30,
        "vad_mode": 1,
        "process_interval_s": 0.4,
        "silence_timeout_s": 0.7,
        "max_segment_s": 4.0,
        "min_speech_s": 0.5,
        "device": None,
    },
    "asr": {
        "model_size": "tiny",
        "device": "auto",
        "compute_type": "auto",
        "hf_endpoint": "https://hf-mirror.com",
    },
    "translate": {
        "source": "en",
        "target": "zh-CN",
        "model_path": "",
    },
    "ui": {
        "position": [200, 600],
        "width": 700,
        "min_width": 500,
        "max_width": 900,
        "height": 150,
        "show_zh": True,
        "font_size_en": 26,
        "font_size_zh": 20,
        "bg_opacity": 0.55,
        "text_color_en": "#FFFFFF",
        "text_color_zh": "#FFD700",
        "fade_out_sec": 6.0,
        "click_through": False,
        "always_on_top": True,
        "font_family": "Microsoft YaHei",
        "obs_mode": "off",
        "theme": "Dark Gold",
        "obs_color": "#00FF00",
        "text_align": "center",
        "auto_start": False,
        "minimal_mode": False,
    },
    "hotkeys": {
        "pause": "Ctrl+Shift+P",
        "show_hide": "Ctrl+Shift+H",
        "copy": "Ctrl+Shift+C",
        "toggle_minimal": "Ctrl+Shift+T",
    },
}


def _deep_merge(base, override):
    """Merge *override* into *base* in-place, preserving base keys."""
    for k, v in override.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v


def load_config():
    """Load config.json, auto-repairing if corrupted or missing keys."""
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.warning("Config load failed (%s), using defaults.", e)
        cfg = {}

    merged = copy.deepcopy(DEFAULT_CONFIG)
    _deep_merge(merged, cfg)

    if cfg != merged:
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(merged, f, indent=2, ensure_ascii=False)
            logger.info("Config repaired and saved.")
        except Exception as e:
            logger.error("Failed to save repaired config: %s", e)

    return merged


def save_config(cfg):
    """Write full config to disk."""
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def save_ui_key(key, value):
    """Update a single UI key in config.json without re-reading the whole file."""
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        cfg["ui"][key] = value
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def get_hotkey_config():
    """Return just the hotkeys section of config."""
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg.get("hotkeys", DEFAULT_CONFIG["hotkeys"])
    except Exception:
        return dict(DEFAULT_CONFIG["hotkeys"])
