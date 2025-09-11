from __future__ import annotations

import json
import math
import os
import traceback
from typing import Optional, Dict, Tuple
import threading

from aqt import gui_hooks, mw
from .. import ems_logging as LOG
from aqt.qt import (
    QWidget,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QPixmap,
    QVBoxLayout,
    QTimer,
    QEvent,
    Qt,
    QMenu,
    QAction,
    QFrame,
    QToolButton,
    QSize,
)


# Paths and simple logging
ADDON_DIR = os.path.dirname(os.path.dirname(__file__))
USER_FILES = os.path.join(ADDON_DIR, "user_files")
STATE_DIR = os.path.join(USER_FILES, "_state")
LOG_PATH = os.path.join(USER_FILES, "log.txt")
STATE_PATH = os.path.join(STATE_DIR, "tamagotchi_state.json")

ASSETS_DIR = os.path.join(ADDON_DIR, "LeoTamagotchi")
CHAR_DIR = os.path.join(ASSETS_DIR, "Character")
UI_DIR = os.path.join(ASSETS_DIR, "UI")
DEVICES_DIR = os.path.join(ASSETS_DIR, "Devices")

# Life stages (extendable)
LIFE_STAGES = ["baby", "kid", "teen", "character"]

# Canonical emotion codes used across stages
EMOTIONS = [
    "default", "angry", "sad", "happy", "loving", "pet",
    "curious", "eating", "sleeping", "cheer", "overjoyed",
]

# Normalized button regions (fractions of 1000x1000 canvas)
BUTTONS = {
    "PET":   {"center": (0.3553, 0.7368), "innerRadius": 0.0447, "outerRadius": 0.0586},
    "SLEEP": {"center": (0.4997, 0.7729), "innerRadius": 0.0470, "outerRadius": 0.0616},
    "FEED":  {"center": (0.6440, 0.7368), "innerRadius": 0.0447, "outerRadius": 0.0586},
}

# ------------------------------ Qt6 compat -----------------------------------
try:
    ASPECT_KEEP = Qt.AspectRatioMode.KeepAspectRatio
except Exception:
    ASPECT_KEEP = getattr(Qt, "KeepAspectRatio", 1)

try:
    RIGHT_BTN = Qt.MouseButton.RightButton
    LEFT_BTN = Qt.MouseButton.LeftButton
except Exception:
    RIGHT_BTN = getattr(Qt, "RightButton", 2)
    LEFT_BTN = getattr(Qt, "LeftButton", 1)

def _win_flag(name: str):
    try:
        return getattr(Qt.WindowType, name)
    except Exception:
        return getattr(Qt, name)

try:
    WA_TRANSLUCENT = Qt.WidgetAttribute.WA_TranslucentBackground
except Exception:
    WA_TRANSLUCENT = getattr(Qt, "WA_TranslucentBackground", 0)

try:
    VIEW_UPDATE_FULL = QGraphicsView.ViewportUpdateMode.FullViewportUpdate
except Exception:
    VIEW_UPDATE_FULL = getattr(QGraphicsView, "FullViewportUpdate", 0)

try:
    VIEW_ANCHOR_CENTER = QGraphicsView.ViewportAnchor.AnchorViewCenter
except Exception:
    VIEW_ANCHOR_CENTER = getattr(QGraphicsView, "AnchorViewCenter", 0)

try:
    SCROLLBAR_OFF = Qt.ScrollBarPolicy.ScrollBarAlwaysOff
except Exception:
    SCROLLBAR_OFF = getattr(Qt, 'ScrollBarAlwaysOff', 1)

# Prepared scale presets (relative to 1000px base)
PRESET_SCALES = [0.18, 0.22, 0.26, 0.30, 0.36, 0.44, 0.55, 0.70, 0.90, 1.20]


class ClickScene(QGraphicsScene):
    """Scene that forwards mouse presses to the window handler first.

    Accepts the event if a button consumed it; otherwise lets normal
    propagation continue.
    """

    def __init__(self, owner):
        super().__init__(owner)
        self._owner = owner
        self.setSceneRect(0, 0, 1000, 1000)
        try:
            self.setBackgroundBrush(Qt.transparent)
        except Exception:
            pass

    def mousePressEvent(self, event):
        try:
            p = event.scenePos()
            if self._owner._handle_button_click(p.x(), p.y()):
                event.accept()
                return
            if event.button() == RIGHT_BTN:
                self._owner._show_size_menu(event.screenPos().toPoint())
                event.accept(); return
            # Begin window drag on left click outside buttons
            if event.button() == LEFT_BTN:
                self._owner._begin_drag(event.screenPos())
        except Exception as e:
            _log_exc("ClickScene mousePressEvent", e)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        try:
            self._owner._drag_to(event.screenPos())
        except Exception:
            pass
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        try:
            self._owner._end_drag()
        except Exception:
            pass
        super().mouseReleaseEvent(event)


class ScalingView(QGraphicsView):
    def __init__(self, scene, owner):
        super().__init__(scene, owner)
        try:
            self.setHorizontalScrollBarPolicy(SCROLLBAR_OFF)
            self.setVerticalScrollBarPolicy(SCROLLBAR_OFF)
        except Exception:
            pass
        try:
            # No frame to blend with PNG transparency if used
            try:
                self.setFrameShape(QFrame.Shape.NoFrame)
            except Exception:
                self.setFrameShape(getattr(QFrame, 'NoFrame'))
        except Exception:
            pass
        try:
            self.setStyleSheet("background: transparent; border: none;")
            self.setAttribute(WA_TRANSLUCENT, True)
            self.viewport().setAttribute(WA_TRANSLUCENT, True)
            self.setViewportUpdateMode(VIEW_UPDATE_FULL)
            self.setTransformationAnchor(VIEW_ANCHOR_CENTER)
            self.setResizeAnchor(VIEW_ANCHOR_CENTER)
        except Exception:
            pass

    def resizeEvent(self, ev):
        try:
            try:
                self.resetTransform()
            except Exception:
                pass
            self.fitInView(self.scene().sceneRect(), ASPECT_KEEP)
        except Exception:
            pass
        super().resizeEvent(ev)

    def wheelEvent(self, ev):
        try:
            if ev.modifiers() & Qt.ControlModifier:
                delta = ev.angleDelta().y()
                factor = 1.0 + (0.1 if delta > 0 else -0.1)
                owner = self.parent()
                if hasattr(owner, "_apply_scale") and hasattr(owner, "_scale"):
                    owner._apply_scale(max(0.2, min(8.0, owner._scale * factor)))
                ev.accept(); return
        except Exception:
            pass
        super().wheelEvent(ev)


def _log(msg: str) -> None:
    try:
        os.makedirs(USER_FILES, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(msg.rstrip() + "\n")
    except Exception:
        # Best-effort; never raise from logger.
        pass


def _log_exc(prefix: str, e: Exception) -> None:
    _log(f"[Tamagotchi] {prefix}: {e}\n{traceback.format_exc()}")


def _ensure_state_dir() -> None:
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
    except Exception as e:
        _log_exc("Failed to create state dir", e)


def _read_state() -> dict:
    try:
        st = {}
        if os.path.exists(STATE_PATH):
            with open(STATE_PATH, "r", encoding="utf-8") as fh:
                st = json.load(fh) or {}
    except Exception as e:
        _log_exc("Failed to read state", e)
        st = {}
    # Defaults
    if "xp" not in st:
        st["xp"] = 0
    if "hunger" not in st:
        st["hunger"] = 8  # 0..8 (empty..full) -> start full
    if "happiness" not in st:
        st["happiness"] = 8  # start full
    if "easy_streak" not in st:
        st["easy_streak"] = 0
    if "again_streak" not in st:
        st["again_streak"] = 0
    # default device selection
    if "device" not in st:
        st["device"] = "CleanUI"  # special value -> uses UI/CleanUI.png
    # life stage defaults
    if "stage" not in st:
        st["stage"] = LIFE_STAGES[0]
    # color tint (optional)
    if "leo_color" not in st:
        st["leo_color"] = ""
    return st


def _write_state(state: dict, push_cloud: bool = True) -> None:
    try:
        _ensure_state_dir()
        with open(STATE_PATH, "w", encoding="utf-8") as fh:
            json.dump(state, fh, ensure_ascii=False, indent=2)
    except Exception as e:
        _log_exc("Failed to write state", e)
    # Best-effort: push to PocketBase in background if logged in
    if push_cloud:
        try:
            # Lazy import to avoid cycles if PB imports this module
            from .. import ems_pocketbase as PB  # type: ignore
            PB.tamagotchi_push_async(state)
        except Exception:
            pass


def _xp_to_stage(xp: int) -> int:
    """Map 0..100 XP into 14 stages (1..14).

    - 0 XP is stage 1
    - 100 XP is clamped to stage 14
    """
    try:
        xp_max = 100.0
        stages = 14
        if xp <= 0:
            return 1
        if xp >= xp_max:
            return stages
        step = xp_max / stages  # ~7.1428
        stage = int(math.floor(xp / step)) + 1
        # Clamp to [1,14]
        return max(1, min(stages, stage))
    except Exception:
        return 1


class LeoTamagotchiWindow(QWidget):
    """Layered scene: CleanUI (base) -> progress bars -> DefaultLeo (top)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Leo Tamagotchi")
        # Frameless, transparent floating widget that stays above Anki UI
        try:
            self.setWindowFlags(_win_flag('FramelessWindowHint') | _win_flag('Tool') | _win_flag('WindowStaysOnTopHint'))
            self.setAttribute(WA_TRANSLUCENT, True)
            self.setStyleSheet("background: transparent;")
        except Exception:
            pass

        layout = QVBoxLayout(self)
        try:
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)
        except Exception:
            pass

        # Build a scene that we can layer images onto
        self.scene = ClickScene(self)
        self.view = ScalingView(self.scene, self)
        layout.addWidget(self.view)

        # Graphics items
        self.ui_item: Optional[QGraphicsPixmapItem] = None
        self.xp_item: Optional[QGraphicsPixmapItem] = None
        self.hunger_item: Optional[QGraphicsPixmapItem] = None
        self.happiness_item: Optional[QGraphicsPixmapItem] = None
        self.leo_item: Optional[QGraphicsPixmapItem] = None
        # XP animation state
        self._current_stage: int = 1
        self._anim_target_stage: Optional[int] = None
        self._anim_timer: Optional[QTimer] = None
        # Hunger animation state
        self._hunger_stage: int = 8
        self._hunger_target_stage: Optional[int] = None
        self._hunger_timer: Optional[QTimer] = None
        # Happiness animation state
        self._happiness_stage: int = 8
        self._happiness_target_stage: Optional[int] = None
        self._happiness_timer: Optional[QTimer] = None

        # Life stage + color
        st = _read_state()
        self._life_stage: str = str(st.get("stage", LIFE_STAGES[0])).lower().strip() or LIFE_STAGES[0]
        if self._life_stage not in LIFE_STAGES:
            self._life_stage = LIFE_STAGES[0]
        self._leo_color: str = str(st.get("leo_color", "") or "").strip()

        # Character switching state
        self._baseline_char: str = "default"
        self._current_char: str = "default"
        self._char_timer: Optional[QTimer] = None
        self._idle_sleeping: bool = False

        self._init_layers()
        # Initial XP/hunger/happiness load
        st = _read_state()
        self.update_xp(st.get("xp", 0), animate=False)
        self._set_hunger_stage(int(st.get("hunger", 8)))
        self._set_happiness_stage(int(st.get("happiness", 8)))
        self.refresh_baseline_character()
        # Apply persisted or default scale/position
        self._scale = float(st.get("scale", 0) or 0)
        if self._scale <= 0:
            self._scale = self._default_scale()
        self._apply_scale(self._scale)
        try:
            x, y = st.get("pos", [None, None])
            if x is not None and y is not None:
                self.move(int(x), int(y))
            else:
                # Default bottom-right placement with margin
                try:
                    scr = self.screen() or (mw and mw.screen())
                    if scr:
                        g = scr.availableGeometry()
                        m = int(16 * (self._scale or 1))
                        self.move(g.right() - self.width() - m, g.bottom() - self.height() - m)
                except Exception:
                    pass
        except Exception:
            pass
        self._drag_origin = None
        # Ensure fitInView happens after layout is realized
        try:
            QTimer.singleShot(0, lambda: self.view.fitInView(self.scene.sceneRect(), ASPECT_KEEP))
        except Exception:
            pass
        # Overlay control buttons (close, -, +)
        self._init_controls()

    def _init_layers(self) -> None:
        try:
            # Base UI
            st = _read_state()
            device = str(st.get("device", "CleanUI") or "CleanUI")
            if device.lower() == "cleanui":
                base_path = os.path.join(UI_DIR, "CleanUI.png")
            else:
                # treat as file stem under Devices; accept both with/without .png
                fn = device
                if not fn.lower().endswith('.png'):
                    fn += ".png"
                base_path = os.path.join(DEVICES_DIR, fn)
                if not os.path.exists(base_path):
                    base_path = os.path.join(UI_DIR, "CleanUI.png")
            ui_pix = QPixmap(base_path)
            try:
                LOG.log("tama.ui.init", device=device, path=base_path)
            except Exception:
                pass
            self.ui_item = self.scene.addPixmap(ui_pix)
            self.ui_item.setZValue(0)

            # XP bar placeholder (updated in update_xp)
            self.xp_item = self.scene.addPixmap(QPixmap())
            self.xp_item.setZValue(1)

            # Hunger bar placeholder
            self.hunger_item = self.scene.addPixmap(QPixmap())
            self.hunger_item.setZValue(1)

            # Happiness bar placeholder
            self.happiness_item = self.scene.addPixmap(QPixmap())
            self.happiness_item.setZValue(1)

            # Character (top layer) - actual pixmap set via baseline stage/emotion
            self.leo_item = self.scene.addPixmap(QPixmap())
            self.leo_item.setZValue(2)
        except Exception as e:
            _log_exc("Failed to initialize layers", e)

    # --- Scaling and persistence ---
    def _default_scale(self) -> float:
        try:
            scr = self.screen() or (mw and mw.screen())
            if scr:
                g = scr.availableGeometry()
                # roughly 18% of the smaller dimension
                target_px = int(min(g.width(), g.height()) * 0.18)
                return max(0.2, min(8.0, target_px / 1000.0))
        except Exception:
            pass
        return 0.3

    def _apply_scale(self, scale: float) -> None:
        try:
            scale = max(0.2, min(8.0, float(scale)))
            s = int(1000 * scale)
            self.setFixedSize(s, s)
            self.view.setFixedSize(s, s)
            try:
                self.view.resetTransform()
            except Exception:
                pass
            self.view.fitInView(self.scene.sceneRect(), ASPECT_KEEP)
            self._scale = scale
            st = _read_state()
            st["scale"] = scale
            st["pos"] = [self.x(), self.y()]
            _write_state(st)
        except Exception as e:
            _log_exc("apply_scale failed", e)

    # --- Device (skin) switching ---
    def set_device(self, device_name: str) -> None:
        """Update base UI device and persist in state (and cloud)."""
        try:
            name = (device_name or "CleanUI").strip()
            if name.lower() == "cleanui":
                path = os.path.join(UI_DIR, "CleanUI.png")
            else:
                fn = name
                if not fn.lower().endswith('.png'):
                    fn += ".png"
                path = os.path.join(DEVICES_DIR, fn)
                if not os.path.exists(path):
                    path = os.path.join(UI_DIR, "CleanUI.png")
            pm = QPixmap(path)
            if self.ui_item is None:
                self.ui_item = self.scene.addPixmap(pm)
                self.ui_item.setZValue(0)
            else:
                self.ui_item.setPixmap(pm)
            # persist
            st = _read_state()
            st["device"] = name if name.lower() == "cleanui" or os.path.exists(path) else "CleanUI"
            _write_state(st)
            try:
                LOG.log("tama.device.set", device=st.get("device"))
            except Exception:
                pass
        except Exception as e:
            _log_exc("set_device failed", e)

    def _show_size_menu(self, global_pos) -> None:
        try:
            m = QMenu(self)
            for label, mul in [("x1",1.0),("x2",2.0),("x4",4.0),("x8",8.0)]:
                act = QAction(label, self)
                act.triggered.connect(lambda checked=False, v=mul: self._apply_scale(v))
                m.addAction(act)
            # Stage info (read-only)
            try:
                m.addSeparator()
                stage_label = QAction(f"Stage: {self._life_stage.title()}", self)
                stage_label.setEnabled(False)
                m.addAction(stage_label)
            except Exception:
                pass
            # Color controls
            try:
                from aqt.qt import QColorDialog
                m.addSeparator()
                pick = QAction("Choose Leo Color…", self)
                def _pick():
                    try:
                        col = QColorDialog.getColor()
                        if col and col.isValid():
                            self.set_leo_color(col.name())
                    except Exception as e:
                        _log_exc("color picker", e)
                pick.triggered.connect(_pick)
                m.addAction(pick)
                for name, hexv in [("None",""),("Blue","#4f46e5"),("Green","#10b981"),("Pink","#ec4899"),("Purple","#a78bfa"),("Cyan","#06b6d4"),("Orange","#f97316")]:
                    actc = QAction(f"Color: {name}", self)
                    actc.triggered.connect(lambda checked=False, v=hexv: self.set_leo_color(v))
                    m.addAction(actc)
            except Exception:
                pass
            m.exec(global_pos)
        except Exception as e:
            _log_exc("size menu failed", e)
        
    def _init_controls(self) -> None:
        try:
            self._btn_close = QToolButton(self)
            self._btn_minus = QToolButton(self)
            self._btn_plus = QToolButton(self)
            for b,t in [(self._btn_close,'×'),(self._btn_minus,'−'),(self._btn_plus,'+')]:
                b.setText(t)
                try: b.setFixedSize(QSize(22,22))
                except Exception: b.setFixedSize(22,22)
                b.setStyleSheet("QToolButton{background:rgba(10,10,12,0.55); color:#fff; border:1px solid rgba(255,255,255,0.35); border-radius:11px; font-weight:600;} QToolButton::hover{background:rgba(10,10,12,0.75);} ")
                b.raise_()
            self._btn_close.clicked.connect(self._on_close_clicked)
            self._btn_minus.clicked.connect(lambda: self._step_scale(-1))
            self._btn_plus.clicked.connect(lambda: self._step_scale(+1))
            self._position_top_buttons()
        except Exception as e:
            _log_exc("init controls failed", e)

    def _position_top_buttons(self) -> None:
        try:
            m = 6
            # right-aligned: [ - ][ + ][ × ]
            x = self.width() - (22*3 + m*4)
            y = m
            self._btn_minus.move(x + m, y)
            self._btn_plus.move(x + m + 22 + m, y)
            self._btn_close.move(x + m + (22+ m)*2, y)
            for b in (self._btn_minus, self._btn_plus, self._btn_close):
                b.raise_()
        except Exception:
            pass

    def _nearest_preset_index(self) -> int:
        s = self._scale or 0.3
        best_i = 0
        best_d = 999
        for i,v in enumerate(PRESET_SCALES):
            d = abs(v - s)
            if d < best_d:
                best_d = d; best_i = i
        return best_i

    def _step_scale(self, direction: int) -> None:
        try:
            idx = self._nearest_preset_index() + (1 if direction>0 else -1)
            idx = max(0, min(len(PRESET_SCALES)-1, idx))
            self._apply_scale(PRESET_SCALES[idx])
            self._position_top_buttons()
        except Exception as e:
            _log_exc("step scale failed", e)

    def _on_close_clicked(self) -> None:
        try:
            disable_for_session()
            self.hide()
        except Exception as e:
            _log_exc("close button failed", e)

    # Dragging window by clicking on background (non-button areas)
    def _begin_drag(self, screen_pos):
        try:
            self._drag_origin = (int(screen_pos.x()), int(screen_pos.y()), self.x(), self.y())
            try:
                LOG.log("tama.drag.begin", x=self.x(), y=self.y())
            except Exception:
                pass
        except Exception:
            self._drag_origin = None

    def _drag_to(self, screen_pos):
        try:
            if not self._drag_origin:
                return
            sx, sy, ox, oy = self._drag_origin
            dx = int(screen_pos.x()) - sx
            dy = int(screen_pos.y()) - sy
            self.move(ox + dx, oy + dy)
        except Exception:
            pass

    def _end_drag(self):
        try:
            self._drag_origin = None
            # Push final position to cloud once at drag end
            st = _read_state(); st["pos"] = [self.x(), self.y()]; _write_state(st, push_cloud=True)
            try:
                LOG.log("tama.drag.end", x=self.x(), y=self.y())
            except Exception:
                pass
        except Exception:
            pass

    def moveEvent(self, ev):
        try:
            # Update local state only; avoid spamming cloud while dragging.
            st = _read_state(); st["pos"] = [self.x(), self.y()]; _write_state(st, push_cloud=False)
        except Exception:
            pass
        try: self._position_top_buttons()
        except Exception: pass
        super().moveEvent(ev)

    def resizeEvent(self, ev):
        try:
            # Keep 1:1 aspect by locking to the chosen scale
            try:
                self.view.resetTransform()
            except Exception:
                pass
            self.view.fitInView(self.scene.sceneRect(), ASPECT_KEEP)
            try: self._position_top_buttons()
            except Exception: pass
        except Exception:
            pass
        super().resizeEvent(ev)

    def _set_stage(self, stage: int) -> None:
        try:
            stage = max(1, min(14, int(stage)))
            if self._current_stage != stage:
                self._current_stage = stage
            xp_path = os.path.join(UI_DIR, f"XPBarProgress{stage}_14.png")
            if self.xp_item is not None:
                self.xp_item.setPixmap(QPixmap(xp_path))
        except Exception as e:
            _log_exc("Failed to set XP stage", e)

    def _set_hunger_stage(self, stage: int) -> None:
        try:
            stage = max(0, min(8, int(stage)))
            self._hunger_stage = stage
            if self.hunger_item is not None:
                hunger_path = os.path.join(UI_DIR, f"Hunger{stage}_8.png")
                self.hunger_item.setPixmap(QPixmap(hunger_path))
            self.refresh_baseline_character()
        except Exception as e:
            _log_exc("Failed to set hunger stage", e)

    def _set_happiness_stage(self, stage: int) -> None:
        try:
            stage = max(0, min(8, int(stage)))
            self._happiness_stage = stage
            if self.happiness_item is not None:
                path = os.path.join(UI_DIR, f"Happiness{stage}_8.png")
                self.happiness_item.setPixmap(QPixmap(path))
            self.refresh_baseline_character()
        except Exception as e:
            _log_exc("Failed to set happiness stage", e)

    # --- Animators for hunger and happiness ---
    def animate_hunger_to(self, target_stage: int) -> None:
        try:
            tgt = max(0, min(8, int(target_stage)))
            if self._hunger_stage == tgt:
                self._set_hunger_stage(tgt)
                return
            self._hunger_target_stage = tgt
            if self._hunger_timer is None:
                self._hunger_timer = QTimer(self)
                self._hunger_timer.setInterval(90)
                def _tick():
                    try:
                        cur = self._hunger_stage
                        tgt2 = self._hunger_target_stage if self._hunger_target_stage is not None else cur
                        if cur == tgt2:
                            self._hunger_timer.stop()
                            return
                        step = 1 if tgt2 > cur else -1
                        self._set_hunger_stage(cur + step)
                    except Exception as e:
                        _log_exc("Hunger animation tick failed", e)
                        self._hunger_timer.stop()
                self._hunger_timer.timeout.connect(_tick)
            if not self._hunger_timer.isActive():
                self._hunger_timer.start()
        except Exception as e:
            _log_exc("Animate hunger failed", e)

    def animate_happiness_to(self, target_stage: int) -> None:
        try:
            tgt = max(0, min(8, int(target_stage)))
            if self._happiness_stage == tgt:
                self._set_happiness_stage(tgt)
                return
            self._happiness_target_stage = tgt
            if self._happiness_timer is None:
                self._happiness_timer = QTimer(self)
                self._happiness_timer.setInterval(90)
                def _tick():
                    try:
                        cur = self._happiness_stage
                        tgt2 = self._happiness_target_stage if self._happiness_target_stage is not None else cur
                        if cur == tgt2:
                            self._happiness_timer.stop()
                            return
                        step = 1 if tgt2 > cur else -1
                        self._set_happiness_stage(cur + step)
                    except Exception as e:
                        _log_exc("Happiness animation tick failed", e)
                        self._happiness_timer.stop()
                self._happiness_timer.timeout.connect(_tick)
            if not self._happiness_timer.isActive():
                self._happiness_timer.start()
        except Exception as e:
            _log_exc("Animate happiness failed", e)

    def update_xp(self, xp: int, animate: bool = True) -> None:
        try:
            stage = _xp_to_stage(int(xp))
            if not animate:
                self._set_stage(stage)
                return

            # Animate transitions to avoid skipping visual stages
            start = self._current_stage
            if start == stage:
                self._set_stage(stage)
                return
            self._anim_target_stage = stage
            if self._anim_timer is None:
                self._anim_timer = QTimer(self)
                self._anim_timer.setInterval(90)
                def _tick():
                    try:
                        tgt = self._anim_target_stage or self._current_stage
                        cur = self._current_stage
                        if cur == tgt:
                            self._anim_timer.stop()
                            return
                        step = 1 if tgt > cur else -1
                        self._set_stage(cur + step)
                    except Exception as e:
                        _log_exc("Animation tick failed", e)
                        self._anim_timer.stop()
                self._anim_timer.timeout.connect(_tick)
            if not self._anim_timer.isActive():
                self._anim_timer.start()
        except Exception as e:
            _log_exc("Failed to update XP layer", e)

    # --- Character management ---
    def _character_path(self, name: str) -> str:
        """Resolve a character asset path by name or canonical emotion for current life stage.

        Accepts both legacy names like 'SadLeo' and canonical ones like 'sad'.
        Falls back to stage default if missing.
        """
        stage = self._life_stage or LIFE_STAGES[0]
        emotion = self._name_to_emotion(name)
        path = self._asset_for_stage_emotion(stage, emotion)
        if not os.path.exists(path):
            # fallback to adult default
            fallback = self._asset_for_stage_emotion("character", "default")
            return fallback
        return path

    def _name_to_emotion(self, name: str) -> str:
        s = (name or "").lower()
        # Canonical direct
        if s in EMOTIONS:
            return s
        # Heuristics for legacy names
        if "angry" in s:
            return "angry"
        if "sad" in s or "cry" in s:
            return "sad"
        if "overjoy" in s:
            return "overjoyed"
        if "cheer" in s or "happy" in s:
            return "happy"
        if "lov" in s:
            return "loving"
        if "pet" in s:
            return "pet"
        if "curious" in s or "learn" in s:
            return "curious"
        if "eat" in s:
            return "eating"
        if "sleep" in s:
            return "sleeping"
        if "default" in s:
            return "default"
        return "default"

    def _asset_for_stage_emotion(self, stage: str, emotion: str) -> str:
        stage = (stage or LIFE_STAGES[0]).lower()
        emotion = (emotion or "default").lower()
        base = ASSETS_DIR
        # Mapping tables (file extensions vary per stage)
        baby = {
            "default": ("CharacterBaby", "BabyDefault.png"),
            "angry":   ("CharacterBaby", "BabyLeoAngry.png"),
            "curious": ("CharacterBaby", "BabyLeoCurious.png"),
            "eating":  ("CharacterBaby", "BabyLeoEating.png"),
            "sleeping":("CharacterBaby", "BabyLeoSleeping.png"),
            # fallbacks for missing baby emotions
            "sad":     ("CharacterBaby", "BabyLeoSleeping.png"),
            "happy":   ("CharacterBaby", "BabyLeoCurious.png"),
            "loving":  ("CharacterBaby", "BabyLeoCurious.png"),
            "pet":     ("CharacterBaby", "BabyLeoCurious.png"),
            "cheer":   ("CharacterBaby", "BabyLeoCurious.png"),
            "overjoyed":("CharacterBaby", "BabyLeoCurious.png"),
        }
        kid = {
            "default": ("CharacterKid", "KidLeoDefault.jpg"),
            "angry":   ("CharacterKid", "KidLeoAngry.jpg"),
            "sad":     ("CharacterKid", "KidLeoCrying.jpg"),
            "happy":   ("CharacterKid", "KidLeoHappy.jpeg"),
            "loving":  ("CharacterKid", "KidLeoLoving.jpeg"),
            "pet":     ("CharacterKid", "KidLeoPet.jpg"),
            "curious": ("CharacterKid", "KidLeoCurious.jpeg"),
            "eating":  ("CharacterKid", "KidLeoEating.jpeg"),
            "sleeping":("CharacterKid", "KidLeoSleeping.jpeg"),
            "cheer":   ("CharacterKid", "KidLeoHappy.jpeg"),
            "overjoyed":("CharacterKid", "KidLeoHappy.jpeg"),
        }
        teen = {
            "default": ("CharacterTeen", "TeenLeoDefault.jpg"),
            "angry":   ("CharacterTeen", "TeenLeoAngry.jpeg"),
            "sad":     ("CharacterTeen", "TeenLeoCrying.jpeg"),
            "happy":   ("CharacterTeen", "TeenLeoHappy.jpeg"),
            "loving":  ("CharacterTeen", "TeenLeoLoving.jpeg"),
            "pet":     ("CharacterTeen", "TeenLeoPet.jpg"),
            "curious": ("CharacterTeen", "TeenLeoCurious.jpeg"),
            "eating":  ("CharacterTeen", "TeenLeoEating.jpg"),
            "sleeping":("CharacterTeen", "TeenLeoSleeping.jpeg"),
            "cheer":   ("CharacterTeen", "TeenLeoHappy.jpeg"),
            "overjoyed":("CharacterTeen", "TeenLeoHappy.jpeg"),
        }
        adult = {
            "default": ("Character", "DefaultLeo.png"),
            "angry":   ("Character", "AngryLeo.png"),
            "sad":     ("Character", "SadLeo.png"),
            "happy":   ("Character", "LeoCheering.png"),
            "loving":  ("Character", "OverjoyedLeo.png"),
            "pet":     ("Character", "LeoBroFistWaiting.png"),
            "curious": ("Character", "LeoCuriousLearning.png"),
            "eating":  ("Character", "LeoStudying.png"),
            "sleeping":("Character", "LeoSleepingInBed.png"),
            "cheer":   ("Character", "LeoCheering.png"),
            "overjoyed":("Character", "OverjoyedLeo.png"),
        }
        table = baby if stage == "baby" else kid if stage == "kid" else teen if stage == "teen" else adult
        folder, fname = table.get(emotion, table.get("default"))
        return os.path.join(base, folder, fname)

    def _apply_character(self, name: str) -> None:
        try:
            self._current_char = name
            path = self._character_path(name)
            pm = QPixmap(path)
            # Apply tint for PNGs only (to avoid coloring JPEG backgrounds)
            try:
                if self._leo_color and path.lower().endswith(".png"):
                    pm = self._tint_pixmap(pm, self._leo_color)
            except Exception:
                pass
            if self.leo_item is not None:
                self.leo_item.setPixmap(pm)
            try:
                LOG.log("tama.emotion.apply", stage=self._life_stage, emotion=self._name_to_emotion(name), path=path)
            except Exception:
                pass
        except Exception as e:
            _log_exc("Failed to apply character", e)

    def _tint_pixmap(self, pm: QPixmap, hex_color: str) -> QPixmap:
        try:
            from aqt.qt import QImage, QColor, QPainter
            img = pm.toImage().convertToFormat(QImage.Format_ARGB32)
            tint = QImage(img.size(), QImage.Format_ARGB32)
            c = QColor(hex_color)
            tint.fill(c)
            # Apply source alpha to tint (mask)
            p = QPainter(tint)
            p.setCompositionMode(QPainter.CompositionMode_DestinationIn)
            p.drawImage(0, 0, img)
            p.end()
            # Multiply overlay over original to preserve shading
            out = QImage(img)
            p2 = QPainter(out)
            p2.setCompositionMode(QPainter.CompositionMode_Multiply)
            p2.drawImage(0, 0, tint)
            p2.end()
            return QPixmap.fromImage(out)
        except Exception:
            return pm

    def _compute_baseline(self) -> str:
        try:
            # If hunger or happiness is 0, baseline is AngryLeo
            if self._hunger_stage == 0 or self._happiness_stage == 0:
                return "angry"
        except Exception:
            pass
        return "default"

    def refresh_baseline_character(self) -> None:
        try:
            # If not in Reviewer, keep Leo sleeping persistently
            if getattr(self, "_idle_sleeping", False):
                if not (self._char_timer and self._char_timer.isActive()):
                    self._apply_character("sleeping")
                return
            self._baseline_char = self._compute_baseline()
            # Only update immediately if no temporary override active
            if not (self._char_timer and self._char_timer.isActive()):
                self._apply_character(self._baseline_char)
        except Exception as e:
            _log_exc("Failed to refresh baseline character", e)

    def show_character_temp(self, name: str, seconds: int = 10) -> None:
        try:
            # Apply character immediately
            self._apply_character(name)
            # Cancel any previous timer and start a fresh single-shot timer
            try:
                if self._char_timer is not None and self._char_timer.isActive():
                    self._char_timer.stop()
            except Exception:
                pass
            self._char_timer = QTimer(self)
            self._char_timer.setSingleShot(True)
            self._char_timer.setInterval(max(1, int(seconds)) * 1000)
            def _on_timeout():
                try:
                    self.refresh_baseline_character()
                except Exception as e:
                    _log_exc("Character single-shot timer failed", e)
            self._char_timer.timeout.connect(_on_timeout)
            self._char_timer.start()
        except Exception as e:
            _log_exc("Failed to show temporary character", e)

    def force_baseline_now(self) -> None:
        """Immediately restore baseline character and cancel any temp timer."""
        try:
            if self._char_timer is not None and self._char_timer.isActive():
                self._char_timer.stop()
            self._char_timer = None
            self._apply_character(self._compute_baseline())
        except Exception as e:
            _log_exc("Failed to force baseline", e)

    def temp_active(self) -> bool:
        try:
            return bool(self._char_timer and self._char_timer.isActive())
        except Exception:
            return False

    # --- Button handling --------------------------------------------------
    def _handle_button_click(self, x: float, y: float) -> bool:
        rect = self.scene.sceneRect() if self.scene else None
        w = rect.width() if rect else 1000
        h = rect.height() if rect else 1000
        def hit(btn):
            cx, cy = BUTTONS[btn]["center"]
            r = BUTTONS[btn]["outerRadius"]  # More forgiving hit area
            cx *= w; cy *= h; r *= max(w, h)
            dx = x - cx; dy = y - cy
            return (dx*dx + dy*dy) <= (r*r)
        try:
            if hit("PET"):
                self._on_pet()
                return True
            if hit("SLEEP"):
                self._on_sleep()
                return True
            if hit("FEED"):
                self._on_feed()
                return True
            # Not a button: log useful debug info once in a while
            try:
                _log(f"[Tamagotchi] Click miss at scene ({x:.1f},{y:.1f}); viewport {w}x{h}")
            except Exception:
                pass
        except Exception as e:
            _log_exc("handle_button_click failed", e)
        return False

    def _on_pet(self) -> None:
        try:
            st = _read_state()
            st["happiness"] = 8
            _write_state(st)
            self.animate_happiness_to(8)
            try:
                LOG.log("tama.action.pet")
            except Exception:
                pass
        except Exception as e:
            _log_exc("pet action failed", e)

    def _on_feed(self) -> None:
        try:
            st = _read_state()
            st["hunger"] = 8
            _write_state(st)
            self.animate_hunger_to(8)
            # Temporary eating reaction
            try:
                self.show_character_temp("eating", seconds=6)
            except Exception:
                pass
            try:
                LOG.log("tama.action.feed")
            except Exception:
                pass
        except Exception as e:
            _log_exc("feed action failed", e)

    def _on_sleep(self) -> None:
        try:
            on_sleep_button()
            # Temporary sleeping reaction
            try:
                self.show_character_temp("sleeping", seconds=8)
            except Exception:
                pass
            try:
                LOG.log("tama.action.sleep")
            except Exception:
                pass
        except Exception as e:
            _log_exc("sleep action failed", e)

    def set_idle_sleeping(self, enabled: bool) -> None:
        """When not reviewing, keep Leo sleeping persistently (no timer)."""
        try:
            self._idle_sleeping = bool(enabled)
            try:
                LOG.log("tama.idle.sleep", enabled=bool(enabled))
            except Exception:
                pass
            if not (self._char_timer and self._char_timer.isActive()):
                if self._idle_sleeping:
                    self._apply_character("sleeping")
                else:
                    self._apply_character(self._compute_baseline())
        except Exception as e:
            _log_exc("idle sleeping toggle failed", e)

    # -------- Stage + color setters --------
    def set_life_stage(self, stage: str) -> None:
        try:
            stage = (stage or LIFE_STAGES[0]).lower()
            if stage not in LIFE_STAGES:
                return
            if self._life_stage != stage:
                self._life_stage = stage
                try:
                    LOG.log("tama.stage.set", stage=stage)
                except Exception:
                    pass
                self.refresh_baseline_character()
        except Exception as e:
            _log_exc("set life stage failed", e)

    def set_leo_color(self, color_hex: Optional[str]) -> None:
        try:
            color = (color_hex or "").strip()
            self._leo_color = color
            st = _read_state(); st["leo_color"] = color; _write_state(st)
            try:
                LOG.log("tama.color.set" if color else "tama.color.reset", color=color)
            except Exception:
                pass
            # Re-apply current character with tint
            self.refresh_baseline_character()
        except Exception as e:
            _log_exc("set color failed", e)


_window_singleton: Optional[LeoTamagotchiWindow] = None
_disabled_for_session: bool = False


def show_tamagotchi() -> None:
    """Create (or focus) the window."""
    global _window_singleton
    try:
        if _disabled_for_session:
            return
        if _window_singleton is None:
            _window_singleton = LeoTamagotchiWindow(mw)
            try:
                LOG.log("tama.window.create")
            except Exception:
                pass
        _window_singleton.show()
        _window_singleton.raise_()
        _window_singleton.activateWindow()
        # Background: attempt to pull newer cloud state and apply
        def _pull_apply():
            try:
                from .. import ems_pocketbase as PB  # type: ignore
                ok, remote, rts, _rid, _msg = PB.tamagotchi_fetch()
                if not ok or remote is None:
                    return
                # Prefer cloud state whenever available (connected)
                # Adopt remote state locally and update UI on the Qt main thread
                def _apply_remote():
                    try:
                        _write_state(remote)
                        if _window_singleton is not None:
                            # Update UI to reflect new state
                            xp = int((remote or {}).get("xp", 0))
                            hunger = int((remote or {}).get("hunger", 8))
                            happiness = int((remote or {}).get("happiness", 8))
                            stage = str((remote or {}).get("stage", LIFE_STAGES[0]))
                            color = str((remote or {}).get("leo_color", "") or "")
                            _window_singleton.update_xp(xp)
                            _window_singleton._set_hunger_stage(hunger)
                            _window_singleton._set_happiness_stage(happiness)
                            _window_singleton.set_life_stage(stage)
                            if color != (_window_singleton._leo_color or ""):
                                _window_singleton.set_leo_color(color)
                            try:
                                LOG.log("tama.remote.adopt", via="pull", xp=xp, hunger=hunger, happiness=happiness, stage=stage)
                            except Exception:
                                pass
                    except Exception as e:
                        _log_exc("apply remote state", e)
                try:
                    # Ensure main thread
                    QTimer.singleShot(0, _apply_remote)
                except Exception:
                    _apply_remote()
            except Exception as e:
                _log_exc("cloud pull", e)
        threading.Thread(target=_pull_apply, daemon=True).start()
    except Exception as e:
        _log_exc("Failed to show Tamagotchi window", e)


def show_temp_character(name: str, seconds: int = 10) -> None:
    try:
        if _window_singleton is not None:
            _window_singleton.show_character_temp(name, seconds=seconds)
    except Exception as e:
        _log_exc("Failed to show temp character (module)", e)


def force_baseline_character() -> None:
    try:
        if _window_singleton is not None:
            _window_singleton.force_baseline_now()
        try:
            LOG.log("tama.baseline.force")
        except Exception:
            pass
    except Exception as e:
        _log_exc("Failed to force baseline (module)", e)

def reset_to_baseline_if_idle() -> None:
    try:
        if _window_singleton is not None and not _window_singleton.temp_active():
            _window_singleton.force_baseline_now()
    except Exception as e:
        _log_exc("Failed to reset baseline if idle", e)


def _on_card_answered_show_question(*args, **kwargs) -> None:
    """When the next card's question is shown, reset to baseline."""
    try:
        # We are in Reviewer; ensure Leo is awake (disable idle sleeping)
        try:
            if _window_singleton is not None:
                _window_singleton.set_idle_sleeping(False)
        except Exception:
            pass
        # Only reset if there is no current temporary reaction showing.
        reset_to_baseline_if_idle()
    except Exception as e:
        _log_exc("Error on show question baseline", e)


def on_sleep_button() -> None:
    """Placeholder for future sleep feature.

    Currently logs an entry; extend later with real behavior (e.g., pause
    decay, show sleeping character/state, etc.).
    """
    try:
        _log("[Tamagotchi] Sleep button pressed (TODO)")
        # Keep a subtle reaction for now: restore baseline quickly
        force_baseline_character()
    except Exception as e:
        _log_exc("Sleep placeholder failed", e)


def disable_for_session() -> None:
    global _disabled_for_session
    _disabled_for_session = True


def sync_now() -> None:
    """Manually sync Tamagotchi state with PocketBase.

    - Pushes local state to the server (create/update)
    - Fetches remote and adopts it if it's newer than the local file
    - Shows user feedback via tooltip
    """
    try:
        from aqt.utils import tooltip, showInfo  # lazy to avoid import cycles
        tooltip("Syncing Tamagotchi...")
    except Exception:
        pass

    def _run():
        try:
            try:
                from .. import ems_pocketbase as PB  # type: ignore
            except Exception:
                # No PB available; nothing to do
                def _notify(msg: str):
                    try:
                        from aqt.utils import tooltip
                        QTimer.singleShot(0, lambda: tooltip(msg))
                    except Exception:
                        pass
                _notify("PocketBase not available.")
                return

            # Ensure login present
            a = PB.load_auth() or {}
            if not a.get("token"):
                def _need_login():
                    try:
                        from aqt.utils import showInfo
                        showInfo("Please log in to PocketBase to sync.")
                    except Exception:
                        pass
                QTimer.singleShot(0, _need_login)
                return

            # Push local
            local = _read_state()
            ok_push, msg_push, rid = PB.tamagotchi_upsert(local)

            # Fetch remote newest
            ok_fetch, remote, rts, _rid, msg_fetch = PB.tamagotchi_fetch()
            # Local timestamp (file mtime)
            try:
                lts = os.path.getmtime(STATE_PATH) if os.path.exists(STATE_PATH) else 0.0
            except Exception:
                lts = 0.0

            adopted = False
            if ok_fetch and remote is not None:
                # Adopt remote and update UI on main thread
                def _apply():
                    try:
                        _write_state(remote)
                        if _window_singleton is not None:
                            xp = int((remote or {}).get("xp", 0))
                            hunger = int((remote or {}).get("hunger", 8))
                            happiness = int((remote or {}).get("happiness", 8))
                            stage = str((remote or {}).get("stage", LIFE_STAGES[0]))
                            color = str((remote or {}).get("leo_color", "") or "")
                            _window_singleton.update_xp(xp)
                            _window_singleton._set_hunger_stage(hunger)
                            _window_singleton._set_happiness_stage(happiness)
                            try:
                                dev = str((remote or {}).get("device", "") or "")
                                if dev:
                                    _window_singleton.set_device(dev)
                            except Exception:
                                pass
                            _window_singleton.set_life_stage(stage)
                            if color != (_window_singleton._leo_color or ""):
                                _window_singleton.set_leo_color(color)
                            try:
                                LOG.log("tama.remote.adopt", via="sync", xp=xp, hunger=hunger, happiness=happiness, stage=stage)
                            except Exception:
                                pass
                    except Exception as e:
                        _log_exc("sync apply", e)
                try:
                    QTimer.singleShot(0, _apply)
                except Exception:
                    _apply()
                adopted = True

            # Notify
            def _done():
                try:
                    from aqt.utils import tooltip
                    if not ok_push and not ok_fetch:
                        tooltip(f"Sync failed: push={msg_push}, fetch={msg_fetch}")
                    elif not ok_push:
                        tooltip(f"Sync partially completed (push failed): {msg_push}")
                    elif adopted:
                        tooltip("Tamagotchi synced (pushed and updated from cloud)")
                    else:
                        tooltip("Tamagotchi synced (pushed)")
                    try:
                        LOG.log("tama.sync", push_ok=bool(ok_push), fetch_ok=bool(ok_fetch), adopted=bool(adopted))
                    except Exception:
                        pass
                except Exception:
                    pass
            QTimer.singleShot(0, _done)
        except Exception as e:
            _log_exc("sync_now thread", e)
            try:
                from aqt.utils import tooltip
                QTimer.singleShot(0, lambda: tooltip(f"Sync error: {e}"))
            except Exception:
                pass

    threading.Thread(target=_run, daemon=True).start()


def add_xp(amount: int) -> None:
    try:
        st = _read_state()
        cur = int(st.get("xp", 0))
        inc = int(amount)
        if inc == 0:
            return
        total = cur + inc
        # Life stage progression: every 100 XP -> next stage
        stage = str(st.get("stage", LIFE_STAGES[0])).lower()
        def _next_stage(s: str) -> str:
            try:
                i = LIFE_STAGES.index(s)
            except Exception:
                i = 0
            return LIFE_STAGES[min(len(LIFE_STAGES)-1, i+1)]
        leveled_up = False
        while total >= 100:
            nxt = _next_stage(stage)
            if nxt == stage:
                # Already at max stage; clamp progress and stop accumulating
                total = 100
                break
            stage = nxt
            total -= 100
            leveled_up = True
            try:
                LOG.log("tama.stage.up", stage=stage)
            except Exception:
                pass
        # Clamp xp to 0..100
        new = max(0, min(100, total))
        st["xp"] = new
        st["stage"] = stage
        _write_state(st)
        if _window_singleton is not None:
            _window_singleton.update_xp(new)
            if leveled_up:
                _window_singleton.set_life_stage(stage)
                # Celebrate briefly
                try:
                    _window_singleton.show_character_temp("happy", seconds=6)
                except Exception:
                    pass
        try:
            LOG.log("tama.xp.add", amount=int(amount), value=new)
        except Exception:
            pass
    except Exception as e:
        _log_exc("Failed to add XP", e)


def decrease_hunger(steps: int = 1) -> None:
    """Decrease hunger by N steps (each step is one bar), clamped to 0.

    Stage mapping: 0..8 (empty..full)."""
    try:
        st = _read_state()
        cur = int(st.get("hunger", 8))
        new = max(0, cur - int(steps))
        if new != cur:
            st["hunger"] = new
            _write_state(st)
            if _window_singleton is not None:
                _window_singleton.animate_hunger_to(new)
            try:
                LOG.log("tama.hunger", value=new)
            except Exception:
                pass
    except Exception as e:
        _log_exc("Failed to decrease hunger", e)


def change_happiness(delta: int) -> None:
    """Change happiness by delta, clamp to 0..8 and update UI/state."""
    try:
        st = _read_state()
        cur = int(st.get("happiness", 8))
        new = max(0, min(8, cur + int(delta)))
        if new != cur:
            st["happiness"] = new
            _write_state(st)
            if _window_singleton is not None:
                _window_singleton.animate_happiness_to(new)
            try:
                LOG.log("tama.happiness", value=new, delta=int(delta))
            except Exception:
                pass
    except Exception as e:
        _log_exc("Failed to change happiness", e)


def _on_card_answered(*args, **kwargs) -> None:
    """Hook: award +10 XP on correct answer.

    We avoid strict signature to support multiple Anki versions:
    - reviewer_did_answer_card(reviewer, card, ease)
    - reviewer_did_answer_card(card, ease)
        # Character switching state
        self._baseline_char: str = "DefaultLeo"
        self._current_char: str = "DefaultLeo"
        self._char_timer: Optional[QTimer] = None
    """
    try:
        ease = None
        if "ease" in kwargs:
            ease = kwargs.get("ease")
        else:
            # last positional arg tends to be the ease integer
            if args and isinstance(args[-1], int):
                ease = args[-1]
        if ease is None:
            return
        # XP only for correct answers
        e = int(ease)
        if e > 1:  # 1=Again (incorrect); >1 considered correct
            add_xp(2)
        # Hunger drops by one on every answered card (any ease)
        decrease_hunger(1)
        # Happiness logic: 0..8 range
        if e <= 1:
            change_happiness(-1)
        elif e == 4:
            change_happiness(+2)
        else:
            change_happiness(+1)

        # Track streaks for character reactions
        st = _read_state()
        if e == 1:
            st["again_streak"] = int(st.get("again_streak", 0)) + 1
            st["easy_streak"] = 0
            _write_state(st)
            show_temp_character("angry", seconds=10)
            if st["again_streak"] >= 3:
                show_temp_character("angry", seconds=10)
        else:
            st["again_streak"] = 0
            if e == 4:
                st["easy_streak"] = int(st.get("easy_streak", 0)) + 1
                _write_state(st)
                if st["easy_streak"] >= 3:
                    show_temp_character("happy", seconds=10)
            else:
                st["easy_streak"] = 0
                _write_state(st)
    except Exception as e:
        _log_exc("Error handling reviewer_did_answer_card", e)


_hooks_registered = False


def setup_hooks() -> None:
    global _hooks_registered
    try:
        if not _hooks_registered:
            gui_hooks.reviewer_did_answer_card.append(_on_card_answered)
            try:
                gui_hooks.reviewer_did_show_question.append(_on_card_answered_show_question)
            except Exception:
                # Fallback: some very old Anki versions may lack this hook
                pass
            # When not reviewing (deck browser, overview), keep Leo sleeping
            def _sleep_now(*a, **k):
                try:
                    if _window_singleton is not None:
                        _window_singleton.set_idle_sleeping(True)
                except Exception:
                    pass
            try:
                gui_hooks.deck_browser_did_render.append(_sleep_now)
            except Exception:
                pass
            try:
                gui_hooks.overview_did_render.append(_sleep_now)
            except Exception:
                pass
            try:
                gui_hooks.reviewer_will_end.append(_sleep_now)
            except Exception:
                pass
            _hooks_registered = True
    except Exception as e:
        _log_exc("Failed to register hooks", e)

def reset_progress() -> None:
    """Reset XP to zero and refill hunger + happiness, then update UI/state."""
    try:
        st = {"xp": 0, "hunger": 8, "happiness": 8, "stage": LIFE_STAGES[0]}
        _write_state(st)
        if _window_singleton is not None:
            _window_singleton.update_xp(0)
            _window_singleton._set_hunger_stage(8)
            _window_singleton._set_happiness_stage(8)
            try:
                _window_singleton.set_life_stage(LIFE_STAGES[0])
            except Exception:
                pass
    except Exception as e:
        _log_exc("Failed to reset progress", e)
