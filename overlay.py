"""
Transparent floating overlay window for displaying real-time captions.
Features: always-on-top, frameless, draggable, resizable, click-through,
fade animations, hover toolbar.
"""

import ctypes
import queue

from PyQt6.QtCore import (
    Qt, pyqtSignal, QPropertyAnimation, QTimer, QEasingCurve
)
from PyQt6.QtGui import QPainter, QColor, QFont, QCursor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QMenu, QSlider,
    QGraphicsOpacityEffect,
    QFrame, QPushButton, QApplication
)

from config import load_config, save_ui_key


THEMES = {
    "Dark Gold": {
        "bg_opacity": 0.55, "text_color_en": "#FFFFFF",
        "text_color_zh": "#FFD700",
    },
    "Pure White": {
        "bg_opacity": 0.75, "text_color_en": "#1a1a1a",
        "text_color_zh": "#333333",
    },
    "Cyber Green": {
        "bg_opacity": 0.65, "text_color_en": "#00FF41",
        "text_color_zh": "#008F11",
    },
    "Warm Orange": {
        "bg_opacity": 0.55, "text_color_en": "#FFFFFF",
        "text_color_zh": "#FF8C00",
    },
    "Nord Blue": {
        "bg_opacity": 0.60, "text_color_en": "#ECEFF4",
        "text_color_zh": "#88C0D0",
    },
}


# ------------------------------------------------------------------
# Caption line
# ------------------------------------------------------------------

class CaptionLine(QFrame):
    """Single line of caption: English text + Chinese translation."""

    def __init__(self, parent=None, font_family="Microsoft YaHei",
                 font_size_en=26, font_size_zh=20,
                 color_en="#FFFFFF", color_zh="#FFD700"):
        super().__init__(parent)
        self.setStyleSheet("background: transparent; border: none;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(2)

        self.label_en = QLabel("")
        self.label_en.setFont(QFont(font_family, font_size_en, QFont.Weight.Bold))
        self.label_en.setStyleSheet(f"color: {color_en}; background: transparent; padding: 0px;")
        self.label_en.setWordWrap(True)
        self.label_en.setTextFormat(Qt.TextFormat.PlainText)
        self.label_en.setMinimumHeight(font_size_en + 4)

        self.label_zh = QLabel("")
        self.label_zh.setFont(QFont(font_family, font_size_zh))
        self.label_zh.setStyleSheet(f"color: {color_zh}; background: transparent; padding: 0px;")
        self.label_zh.setWordWrap(True)
        self.label_zh.setTextFormat(Qt.TextFormat.PlainText)
        self.label_zh.setMinimumHeight(font_size_zh + 4)

        layout.addWidget(self.label_en)
        layout.addWidget(self.label_zh)

    def set_alignment(self, align):
        a = {"left": Qt.AlignmentFlag.AlignLeft,
             "center": Qt.AlignmentFlag.AlignCenter,
             "right": Qt.AlignmentFlag.AlignRight}.get(align, Qt.AlignmentFlag.AlignLeft)
        self.label_en.setAlignment(a | Qt.AlignmentFlag.AlignVCenter)
        self.label_zh.setAlignment(a | Qt.AlignmentFlag.AlignVCenter)

    def set_text(self, en_text, zh_text):
        self.label_en.setText(en_text)
        self.label_zh.setText(zh_text if zh_text else "")

    def set_font_size_en(self, size):
        font = self.label_en.font()
        font.setPointSize(size)
        self.label_en.setFont(font)

    def set_font_size_zh(self, size):
        font = self.label_zh.font()
        font.setPointSize(size)
        self.label_zh.setFont(font)


# ------------------------------------------------------------------
# Hover toolbar button
# ------------------------------------------------------------------

class _ToolbarFrame(QFrame):
    """Toolbar container that cancels hide timer on mouse enter."""

    def __init__(self, parent, hide_timer):
        super().__init__(parent)
        self._hide_timer = hide_timer

    def enterEvent(self, event):
        self._hide_timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hide_timer.start(600)
        super().leaveEvent(event)


class ToolButton(QPushButton):
    """Small round semi-transparent button for the hover toolbar."""

    _BASE = (
        "QPushButton {"
        "  background: rgba(255,255,255,0.12);"
        "  border: 1px solid rgba(255,255,255,0.2);"
        "  border-radius: 13px;"
        "  color: #ddd;"
        "  font-size: 13px;"
        "  padding: 0px;"
        "}"
        "QPushButton:hover {"
        "  background: rgba(255,255,255,0.35);"
        "  border: 1px solid rgba(255,255,255,0.5);"
        "  color: #fff;"
        "}"
    )

    _ACTIVE = (
        "QPushButton {"
        "  background: rgba(255,255,255,0.45);"
        "  border: 1px solid rgba(255,255,255,0.65);"
        "  border-radius: 13px;"
        "  color: #fff;"
        "  font-size: 13px;"
        "  padding: 0px;"
        "}"
        "QPushButton:hover {"
        "  background: rgba(255,255,255,0.55);"
        "  border: 1px solid rgba(255,255,255,0.8);"
        "  color: #fff;"
        "}"
    )

    def __init__(self, text, tooltip, parent=None):
        super().__init__(text, parent)
        self.setToolTip(tooltip)
        self.setFixedSize(26, 26)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setStyleSheet(self._BASE)
        self._active = False

    def set_active(self, active):
        self._active = active
        self.setStyleSheet(self._ACTIVE if active else self._BASE)


# ------------------------------------------------------------------
# Overlay window
# ------------------------------------------------------------------

class OverlayWindow(QWidget):
    """Main transparent overlay window.

    Text updates come from a thread-safe queue polled by a QTimer.
    """

    signal_pause = pyqtSignal(bool)
    signal_open_settings = pyqtSignal()

    _RESIZE_MARGIN = 7

    def __init__(self):
        super().__init__()
        self._cfg = load_config()
        self._ui = self._cfg["ui"]

        # --- State ---
        self._paused = False
        self._click_through = self._ui.get("click_through", False)
        self._show_zh = self._ui.get("show_zh", True)
        self._lock_fade = False
        self._pin_position = False
        self._obs_mode = self._ui.get("obs_mode", "off")  # "off" | "green" | "blue"
        self._cur_theme = self._ui.get("theme", "Dark Gold")
        self._minimal_mode = self._ui.get("minimal_mode", False)

        # --- Drag / resize ---
        self._drag_pos = None
        self._resize_edge = None
        self._resize_origin_geo = None

        # --- Text queue ---
        self._text_queue = None
        self._current_en = ""
        self._current_zh = ""
        self._poll_timer = None

        self._init_window()
        self._init_content()
        self._init_fade_timer()

        self.signal_pause.connect(self._on_pause)

        self._apply_theme()
        self._set_minimal(self._minimal_mode)

    # ------------------------------------------------------------------
    # Queue wiring
    # ------------------------------------------------------------------

    def set_text_queue(self, q):
        self._text_queue = q
        self._poll_timer = QTimer(self)
        self._poll_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._poll_timer.timeout.connect(self._poll_text)
        self._poll_timer.start(30)

    # ------------------------------------------------------------------
    # Window setup
    # ------------------------------------------------------------------

    def _init_window(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setMouseTracking(True)
        self.setWindowTitle("EchoCap")

        # Respect always_on_top config
        if not self._ui.get("always_on_top", True):
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, False)
            # re-show needed after flag change
            self.hide()
            self.show()

        self.setMinimumWidth(self._ui.get("min_width", 500))
        self.setMaximumWidth(self._ui.get("max_width", 900))
        self.setMinimumHeight(110)
        self.setMaximumHeight(600)

        # Initial size from config, or defaults
        w = self._ui.get("width", 700)
        h = self._ui.get("height", 150)
        self.resize(w, h)

        pos = self._ui.get("position", [200, 600])
        self.move(pos[0], pos[1])

        # Opacity effect for fades
        self._opacity_effect = QGraphicsOpacityEffect(self)
        self._opacity_effect.setOpacity(1.0)
        self.setGraphicsEffect(self._opacity_effect)

        self._fade_anim = QPropertyAnimation(self._opacity_effect, b"opacity")
        self._fade_anim.setDuration(400)
        self._fade_anim.setEasingCurve(QEasingCurve.Type.InOutCubic)

    # ------------------------------------------------------------------
    # Content
    # ------------------------------------------------------------------

    def _init_content(self):
        self._main_layout = QVBoxLayout(self)
        self._main_layout.setContentsMargins(12, 8, 12, 8)
        self._main_layout.setSpacing(2)

        # Hide-toolbar timer (created before toolbar)
        self._toolbar_hide_timer = QTimer(self)
        self._toolbar_hide_timer.setSingleShot(True)
        self._toolbar_hide_timer.timeout.connect(self._hide_toolbar_if_left)

        # Resize debounce timer — prevents layout thrash at min size
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(50)
        self._resize_timer.timeout.connect(self._on_resize_done)

        # --- Toolbar row ---
        self._toolbar = _ToolbarFrame(self, self._toolbar_hide_timer)
        self._toolbar.setFixedHeight(30)
        self._toolbar.setStyleSheet("background: transparent; border: none;")
        self._toolbar.hide()

        tb_layout = QHBoxLayout(self._toolbar)
        tb_layout.setContentsMargins(4, 0, 0, 0)
        tb_layout.setSpacing(3)

        # --- Opacity slider ---
        self._opacity_slider = QSlider(Qt.Orientation.Horizontal, self._toolbar)
        self._opacity_slider.setRange(10, 90)
        self._opacity_slider.setValue(int(self._ui.get("bg_opacity", 0.55) * 100))
        self._opacity_slider.setFixedWidth(50)
        self._opacity_slider.setToolTip("Background opacity")
        self._opacity_slider.valueChanged.connect(self._on_opacity_slider)
        self._opacity_slider.sliderReleased.connect(self._save_opacity)
        tb_layout.addWidget(self._opacity_slider)

        tb_layout.addStretch()

        # --- Buttons ---
        self._btn_lock_fade = ToolButton("📌", "Lock: prevent auto-hide", self._toolbar)
        self._btn_lock_fade.clicked.connect(self._toggle_lock_fade)

        self._btn_pin = ToolButton("📍", "Pin: prevent dragging", self._toolbar)
        self._btn_pin.clicked.connect(self._toggle_pin)

        self._btn_copy = ToolButton("📋", "Copy to clipboard", self._toolbar)
        self._btn_copy.clicked.connect(self._copy_text)

        self._btn_font_plus = ToolButton("A⁺", "Increase EN font size", self._toolbar)
        self._btn_font_plus.clicked.connect(self._font_plus)

        self._btn_font_minus = ToolButton("A⁻", "Decrease EN font size", self._toolbar)
        self._btn_font_minus.clicked.connect(self._font_minus)

        self._btn_zh_font_plus = ToolButton("中⁺", "Increase ZH font size", self._toolbar)
        self._btn_zh_font_plus.clicked.connect(self._zh_font_plus)

        self._btn_zh_font_minus = ToolButton("中⁻", "Decrease ZH font size", self._toolbar)
        self._btn_zh_font_minus.clicked.connect(self._zh_font_minus)

        self._btn_obs = ToolButton("🎬", "OBS mode: off→green→blue", self._toolbar)
        self._btn_obs.clicked.connect(self._cycle_obs)
        self._update_obs_button()

        self._btn_theme = ToolButton("🎨", "Switch color theme", self._toolbar)
        self._btn_theme.clicked.connect(self._cycle_theme)

        self._btn_settings = ToolButton("⚙", "Open settings", self._toolbar)
        self._btn_settings.clicked.connect(self._open_settings)

        self._btn_minimal = ToolButton("⊟", "Toggle minimal mode", self._toolbar)
        self._btn_minimal.clicked.connect(lambda: self._set_minimal(not self._minimal_mode))

        self._btn_pos_bottom = ToolButton("⬇", "Move to bottom center", self._toolbar)
        self._btn_pos_bottom.clicked.connect(lambda: self._move_to_preset("bottom"))
        self._btn_pos_top = ToolButton("⬆", "Move to top center", self._toolbar)
        self._btn_pos_top.clicked.connect(lambda: self._move_to_preset("top"))

        for b in [self._btn_lock_fade, self._btn_pin,
                   self._btn_copy, self._btn_font_plus, self._btn_font_minus,
                   self._btn_zh_font_plus, self._btn_zh_font_minus,
                   self._btn_obs, self._btn_theme, self._btn_settings,
                   self._btn_minimal,
                   self._btn_pos_bottom, self._btn_pos_top]:
            tb_layout.addWidget(b)

        # Toolbar floats absolutely — not in the main layout.
        self._toolbar.adjustSize()
        self._toolbar.move(self.width() - self._toolbar.width() - 10, 8)

        # --- Caption line ---
        self._caption_line = CaptionLine(
            parent=self,
            font_family=self._ui.get("font_family", "Microsoft YaHei"),
            font_size_en=self._ui.get("font_size_en", 26),
            font_size_zh=self._ui.get("font_size_zh", 20),
            color_en=self._ui.get("text_color_en", "#FFFFFF"),
            color_zh=self._ui.get("text_color_zh", "#FFD700"),
        )
        self._main_layout.addWidget(self._caption_line)

        # Apply initial text alignment
        self._caption_line.set_alignment(self._ui.get("text_align", "left"))

        # Toolbar must be on top of caption to receive clicks
        self._toolbar.raise_()

    # ------------------------------------------------------------------
    # Fade timer
    # ------------------------------------------------------------------

    def _init_fade_timer(self):
        self._fade_timer = QTimer(self)
        self._fade_timer.setSingleShot(True)
        self._fade_timer.timeout.connect(self._start_fade_out)

    # ------------------------------------------------------------------
    # Text polling
    # ------------------------------------------------------------------

    def _poll_text(self):
        if self._paused or self._text_queue is None:
            return

        latest = None
        while True:
            try:
                latest = self._text_queue.get_nowait()
            except queue.Empty:
                break

        if latest is None:
            return

        en, zh = latest
        self._current_en = en
        self._current_zh = zh
        self._apply_text()

    def _apply_text(self):
        if self._paused:
            return
        en = self._current_en
        zh = self._current_zh
        if not zh:
            zh = self._caption_line.label_zh.text()
        if not self._show_zh:
            zh = ""
        self._caption_line.set_text(en, zh)
        self._cancel_fade()
        self._fade_in()
        if not self._lock_fade:
            self._reset_fade_timer()
        self.repaint()

    def show_text(self, en_text, zh_text):
        self._current_en = en_text
        self._current_zh = zh_text
        self._apply_text()

    def _on_pause(self, paused):
        self._paused = paused

    # ------------------------------------------------------------------
    # Fade animations
    # ------------------------------------------------------------------

    def _fade_in(self):
        self._fade_anim.stop()
        current = self._opacity_effect.opacity()
        if current >= 0.99:
            self._opacity_effect.setOpacity(1.0)
            self.repaint()
            return
        self._fade_anim.setStartValue(current)
        self._fade_anim.setEndValue(1.0)
        self._fade_anim.setDuration(180)
        self._fade_anim.start()

    def _start_fade_out(self):
        if self._lock_fade:
            return
        self._fade_anim.stop()
        self._fade_anim.setStartValue(self._opacity_effect.opacity())
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.setDuration(800)
        self._fade_anim.start()

    def _cancel_fade(self):
        self._fade_anim.stop()
        self._fade_timer.stop()

    def _reset_fade_timer(self):
        if self._lock_fade:
            return
        sec = self._ui.get("fade_out_sec", 6.0)
        self._fade_timer.start(int(sec * 1000))

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self._obs_mode in ("green", "blue"):
            color = QColor("#00FF00" if self._obs_mode == "green" else "#0000FF")
            painter.setBrush(color)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(self.rect(), 14, 14)
        else:
            alpha = int(self._ui.get("bg_opacity", 0.55) * 255)
            painter.setBrush(QColor(0, 0, 0, alpha))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(self.rect(), 14, 14)

    # ------------------------------------------------------------------
    # Resize edge detection
    # ------------------------------------------------------------------

    def _get_resize_edge(self, pos):
        m = self._RESIZE_MARGIN
        x, y = pos.x(), pos.y()
        w, h = self.width(), self.height()
        l = x < m
        r = x > w - m
        t = y < m
        b = y > h - m
        if t and l:   return 'tl'
        if t and r:   return 'tr'
        if b and l:   return 'bl'
        if b and r:   return 'br'
        if l:         return 'l'
        if r:         return 'r'
        if t:         return 't'
        if b:         return 'b'
        return None

    def _cursor_for_edge(self, edge):
        if edge in ('tl', 'br'):
            return Qt.CursorShape.SizeFDiagCursor
        if edge in ('tr', 'bl'):
            return Qt.CursorShape.SizeBDiagCursor
        if edge in ('l', 'r'):
            return Qt.CursorShape.SizeHorCursor
        if edge in ('t', 'b'):
            return Qt.CursorShape.SizeVerCursor
        return Qt.CursorShape.ArrowCursor

    # ------------------------------------------------------------------
    # Mouse events
    # ------------------------------------------------------------------

    def enterEvent(self, event):
        self._toolbar_hide_timer.stop()
        self._toolbar.show()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._toolbar_hide_timer.start(400)
        super().leaveEvent(event)

    def _hide_toolbar_if_left(self):
        if not self.rect().contains(self.mapFromGlobal(QCursor.pos())):
            self._toolbar.hide()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            self._show_context_menu(event.globalPosition().toPoint())
            return

        if event.button() != Qt.MouseButton.LeftButton or self._click_through:
            return

        local = event.position().toPoint()
        edge = self._get_resize_edge(local)

        if edge and not self._pin_position:
            self._resize_edge = edge
            self._resize_origin_geo = self.geometry()
            self._drag_pos = event.globalPosition().toPoint()
        elif not self._pin_position:
            self._resize_edge = None
            self._drag_pos = event.globalPosition().toPoint()

    def mouseMoveEvent(self, event):
        local = event.position().toPoint()

        if self._resize_edge:
            delta = event.globalPosition().toPoint() - self._drag_pos
            geo = QWidget.geometry(self)  # use base class to get unmodified
            x, y, w, h = geo.x(), geo.y(), geo.width(), geo.height()

            min_w = self.minimumWidth()
            max_w = self.maximumWidth()
            min_h = self.minimumHeight()
            max_h = self.maximumHeight()

            e = self._resize_edge

            if 'r' in e:
                w = max(min_w, min(max_w, self._resize_origin_geo.width() + delta.x()))
            if 'l' in e:
                new_w = max(min_w, min(max_w, self._resize_origin_geo.width() - delta.x()))
                x = self._resize_origin_geo.x() + (self._resize_origin_geo.width() - new_w)
                w = new_w
            if 'b' in e:
                h = max(min_h, min(max_h, self._resize_origin_geo.height() + delta.y()))
            if 't' in e:
                new_h = max(min_h, min(max_h, self._resize_origin_geo.height() - delta.y()))
                y = self._resize_origin_geo.y() + (self._resize_origin_geo.height() - new_h)
                h = new_h

            self.setGeometry(x, y, w, h)
            return

        if self._drag_pos is not None:
            delta = event.globalPosition().toPoint() - self._drag_pos
            self.move(self.pos() + delta)
            self._drag_pos = event.globalPosition().toPoint()
            return

        # No action — just update cursor hint
        edge = self._get_resize_edge(local)
        if edge and not self._pin_position:
            self.setCursor(self._cursor_for_edge(edge))
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self._resize_edge:
                self._resize_edge = None
                save_ui_key("width", self.width())
                save_ui_key("height", self.height())
            elif self._drag_pos is not None:
                save_ui_key("position", [self.x(), self.y()])
            self._drag_pos = None

    # ------------------------------------------------------------------
    # Context menu
    # ------------------------------------------------------------------

    def _show_context_menu(self, pos):
        menu = QMenu(self)

        if self._paused:
            a = menu.addAction("Resume")
            a.triggered.connect(lambda: self.signal_pause.emit(False))
        else:
            a = menu.addAction("Pause")
            a.triggered.connect(lambda: self.signal_pause.emit(True))

        menu.addSeparator()

        ex = menu.addAction("Exit")
        ex.triggered.connect(QApplication.instance().quit)

        menu.exec(pos)

    # ------------------------------------------------------------------
    # Click-through
    # ------------------------------------------------------------------

    def _toggle_click_through(self):
        self._click_through = not self._click_through
        save_ui_key("click_through", self._click_through)
        self._apply_click_through(self._click_through)

    def _apply_click_through(self, enabled):
        hwnd = int(self.winId())
        GWL_EXSTYLE = -20
        WS_EX_TRANSPARENT = 0x20
        style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        if enabled:
            style |= WS_EX_TRANSPARENT
        else:
            style &= ~WS_EX_TRANSPARENT
        ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)

    # ------------------------------------------------------------------
    # Toolbar actions
    # ------------------------------------------------------------------

    def _toggle_zh(self):
        self._show_zh = not self._show_zh
        save_ui_key("show_zh", self._show_zh)
        self._apply_text()

    def _toggle_lock_fade(self):
        self._lock_fade = not self._lock_fade
        self._btn_lock_fade.set_active(self._lock_fade)
        if self._lock_fade:
            self._cancel_fade()
            self._fade_in()

    def _toggle_pin(self):
        self._pin_position = not self._pin_position
        self._btn_pin.set_active(self._pin_position)

    def _copy_text(self):
        en = self._current_en
        zh = self._current_zh or self._caption_line.label_zh.text()
        text = f"{en}\n{zh}" if zh else en
        if text.strip():
            QApplication.clipboard().setText(text.strip())

    def _font_plus(self):
        fs = self._ui.get("font_size_en", 26) + 2
        self._ui["font_size_en"] = fs
        self._caption_line.set_font_size_en(fs)
        save_ui_key("font_size_en", fs)

    def _font_minus(self):
        fs = max(14, self._ui.get("font_size_en", 26) - 2)
        self._ui["font_size_en"] = fs
        self._caption_line.set_font_size_en(fs)
        save_ui_key("font_size_en", fs)

    def _zh_font_plus(self):
        fs = self._ui.get("font_size_zh", 20) + 2
        self._ui["font_size_zh"] = fs
        self._caption_line.set_font_size_zh(fs)
        save_ui_key("font_size_zh", fs)

    def _zh_font_minus(self):
        fs = max(12, self._ui.get("font_size_zh", 20) - 2)
        self._ui["font_size_zh"] = fs
        self._caption_line.set_font_size_zh(fs)
        save_ui_key("font_size_zh", fs)

    # --- Opacity slider ---

    def _on_opacity_slider(self, value):
        self._ui["bg_opacity"] = value / 100.0
        self.repaint()

    def _save_opacity(self):
        save_ui_key("bg_opacity", self._ui["bg_opacity"])

    # --- OBS mode ---

    def _cycle_obs(self):
        if self._obs_mode == "off":
            self._obs_mode = "green"
        elif self._obs_mode == "green":
            self._obs_mode = "blue"
        else:
            self._obs_mode = "off"
        self._ui["obs_mode"] = self._obs_mode
        save_ui_key("obs_mode", self._obs_mode)
        self._update_obs_button()
        self.repaint()

    def _update_obs_button(self):
        if self._obs_mode == "off":
            self._btn_obs.setText("🎬")
            self._btn_obs.setToolTip("OBS mode: off → green → blue")
            self._btn_obs.set_active(False)
        elif self._obs_mode == "green":
            self._btn_obs.setText("🟢")
            self._btn_obs.setToolTip("OBS mode: green chroma key")
            self._btn_obs.set_active(True)
        else:
            self._btn_obs.setText("🔵")
            self._btn_obs.setToolTip("OBS mode: blue chroma key")
            self._btn_obs.set_active(True)

    # --- Theme ---

    def _cycle_theme(self):
        keys = list(THEMES.keys())
        idx = keys.index(self._cur_theme) if self._cur_theme in keys else 0
        idx = (idx + 1) % len(keys)
        self._cur_theme = keys[idx]
        self._apply_theme()
        save_ui_key("theme", self._cur_theme)

    def _apply_theme(self):
        theme = THEMES.get(self._cur_theme, THEMES["Dark Gold"])
        for k, v in theme.items():
            self._ui[k] = v
            save_ui_key(k, v)
        color_en = self._ui.get("text_color_en", "#FFFFFF")
        color_zh = self._ui.get("text_color_zh", "#FFD700")
        self._caption_line.label_en.setStyleSheet(
            f"color: {color_en}; background: transparent; padding: 0px;")
        self._caption_line.label_zh.setStyleSheet(
            f"color: {color_zh}; background: transparent; padding: 0px;")
        self._opacity_slider.blockSignals(True)
        self._opacity_slider.setValue(int(self._ui.get("bg_opacity", 0.55) * 100))
        self._opacity_slider.blockSignals(False)
        self.repaint()

    # --- Settings ---

    def _set_minimal(self, enabled):
        self._minimal_mode = enabled
        self._btn_minimal.set_active(enabled)
        if enabled:
            self._caption_line.label_zh.hide()
            self.setMinimumHeight(50)
            self._btn_zh_font_plus.hide()
            self._btn_zh_font_minus.hide()
        else:
            if self._show_zh:
                self._caption_line.label_zh.show()
            self.setMinimumHeight(110)
            self._btn_zh_font_plus.show()
            self._btn_zh_font_minus.show()
        self._ui["minimal_mode"] = enabled
        save_ui_key("minimal_mode", enabled)

    def _move_to_preset(self, position):
        screen = QApplication.primaryScreen()
        if not screen:
            return
        geo = screen.availableGeometry()
        x = (geo.width() - self.width()) // 2
        if position == "bottom":
            y = geo.height() - self.height() - 80
        else:
            y = 40
        self.move(x, y)
        save_ui_key("position", [self.x(), self.y()])

    def _open_settings(self):
        self.signal_open_settings.emit()

    # ------------------------------------------------------------------
    # Resize
    # ------------------------------------------------------------------

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Reposition toolbar immediately (cheap), defer repaint to avoid jank
        if hasattr(self, '_toolbar') and self._toolbar:
            self._toolbar.adjustSize()
            self._toolbar.move(self.width() - self._toolbar.width() - 10, 8)
        self._resize_timer.start()

    def _on_resize_done(self):
        self.repaint()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def center_on_screen(self):
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            x = (geo.width() - self.width()) // 2
            y = geo.height() - self.height() - 120
            self.move(x, y)
