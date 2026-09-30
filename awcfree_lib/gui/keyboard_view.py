"""The on-screen keyboard.

Drawn from the measured layout, so this is the real key arrangement of this
machine rather than a picture of a generic keyboard: positions come from
`layout.CELLS`, which was obtained by lighting each LED and locating it with a
camera, and widths from the table in `model.WIDE_KEYS`.

Every key is painted by hand instead of being a child widget.  Eighty-five widgets
each with a drop-shadow effect is slow and looks flat; one custom paint pass can
draw the glow a lit key throws onto the board around it, which is the thing that
makes the rendering read as light rather than as coloured rectangles.
"""
from __future__ import annotations

from PyQt6.QtCore import QPointF, QRect, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient,
)
from PyQt6.QtWidgets import QWidget

from . import theme
from .model import keyboard_layout

Rgb = tuple[int, int, int]


class KeyboardView(QWidget):
    """Interactive rendering of the 85 wired keys.

    Click to select, drag to sweep a selection, shift to add, ctrl to remove.
    `selectionChanged` carries the current set of LED ids.
    """

    selectionChanged = pyqtSignal(set)
    keyActivated = pyqtSignal(int)

    #: Painted size of one grid cell, before the widget scales to fit.
    UNIT = 46.0
    GAP = 5.0

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.keys = keyboard_layout()
        self.cols = max(k["col"] + k["w"] for k in self.keys)
        self.rows = max(k["row"] for k in self.keys) + 1
        self.colours: dict[int, Rgb] = {k["id"]: (0, 0, 0) for k in self.keys}
        self.selection: set[int] = set()
        self._hover: int | None = None
        self._rects: dict[int, QRectF] = {}
        self._drag_mode: str | None = None
        self._dragged: set[int] = set()
        self._board = QRectF()
        self._dim = False
        self.setMouseTracking(True)
        self.setMinimumSize(560, 210)
        self.setFont(theme.ui_font(8, theme.QFont.Weight.DemiBold))

    # --- state -------------------------------------------------------------
    def setDim(self, dim: bool) -> None:
        """Fade the board when another part has focus.

        The picture stays on screen because it is what the machine looks like, but
        fading it says plainly that clicks here will not do anything right now.
        """
        if dim != self._dim:
            self._dim = dim
            self.update()

    def set_colours(self, colours: dict[int, Rgb]) -> None:
        self.colours.update(colours)
        self.update()

    def set_selection(self, leds: set[int]) -> None:
        self.selection = set(leds)
        self.selectionChanged.emit(set(self.selection))
        self.update()

    def select_all(self) -> None:
        self.set_selection({k["id"] for k in self.keys})

    def clear_selection(self) -> None:
        self.set_selection(set())

    def targets(self) -> list[int]:
        """Which keys an action applies to: the selection, or everything."""
        return sorted(self.selection) if self.selection else [k["id"] for k in self.keys]

    # --- geometry ----------------------------------------------------------
    def _board_size(self) -> tuple[float, float]:
        w = self.cols * self.UNIT + (self.cols - 1) * self.GAP
        h = self.rows * self.UNIT + (self.rows - 1) * self.GAP
        return w, h

    def _layout_rects(self) -> float:
        """Place every key for the current widget size; returns the scale used."""
        bw, bh = self._board_size()
        pad = 26.0
        scale = min((self.width() - pad * 2) / bw, (self.height() - pad * 2) / bh)
        scale = max(scale, 0.2)
        ox = (self.width() - bw * scale) / 2
        oy = (self.height() - bh * scale) / 2
        unit, gap = self.UNIT * scale, self.GAP * scale
        self._rects = {}
        for k in self.keys:
            x = ox + k["col"] * (unit + gap)
            y = oy + k["row"] * (unit + gap)
            w = k["w"] * unit + (k["w"] - 1) * gap
            self._rects[k["id"]] = QRectF(x, y, w, unit)
        # The deck is drawn around the keys rather than filling the widget, so a
        # tall window does not leave a large empty slab above and below them.
        inset = 22 * scale
        self._board = QRectF(ox - inset, oy - inset,
                             bw * scale + inset * 2, bh * scale + inset * 2)
        return scale

    def _at(self, pos: QPointF) -> int | None:
        for led, rect in self._rects.items():
            if rect.contains(pos):
                return led
        return None

    # --- painting ----------------------------------------------------------
    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        scale = self._layout_rects()
        radius = 8 * scale

        self._paint_deck(p)

        # Pass one: the glow each lit key throws onto the deck. Drawn for every key
        # first so a bright neighbour's halo sits *under* the key faces, not over
        # them, which is how it looks on the real keyboard.
        p.setPen(Qt.PenStyle.NoPen)
        for led, rect in self._rects.items():
            colour = self.colours.get(led, (0, 0, 0))
            if max(colour) < 12:
                continue
            self._paint_glow(p, rect, colour, scale)

        # Pass two: the key faces.
        for k in self.keys:
            led = k["id"]
            self._paint_key(p, self._rects[led], k, self.colours.get(led, (0, 0, 0)),
                            radius, scale)

        if self._dim:
            veil = QPainterPath()
            veil.addRoundedRect(self._board, theme.RADIUS, theme.RADIUS)
            p.fillPath(veil, QColor(6, 7, 11, 150))
        p.end()

    def _paint_deck(self, p: QPainter) -> None:
        """The chassis the keys sit in."""
        r = self._board
        grad = QLinearGradient(r.topLeft(), r.bottomLeft())
        grad.setColorAt(0.0, QColor("#24323c"))
        grad.setColorAt(0.55, QColor("#111c25"))
        grad.setColorAt(1.0, QColor("#0c141c"))
        path = QPainterPath()
        path.addRoundedRect(r, theme.RADIUS, theme.RADIUS)
        p.fillPath(path, grad)
        p.setPen(QPen(QColor(255, 255, 255, 16), 1))
        p.drawPath(path)

    def _paint_glow(self, p: QPainter, rect: QRectF, colour: Rgb, scale: float) -> None:
        """Two overlapping halos: a wide soft bloom and a tight bright core.

        One gradient alone either spreads far and looks washed out, or stays tight
        and looks like a border. Two gives the falloff real light has.
        """
        c = QColor(*colour)
        strength = max(colour) / 255.0
        for spread, alpha_in, alpha_mid in ((52 * scale, 60, 20), (22 * scale, 150, 60)):
            area = rect.adjusted(-spread, -spread, spread, spread)
            grad = QRadialGradient(rect.center(),
                                   max(area.width(), area.height()) / 2)
            a = QColor(c); a.setAlpha(int(alpha_in * strength))
            b = QColor(c); b.setAlpha(int(alpha_mid * strength))
            grad.setColorAt(0.0, a)
            grad.setColorAt(0.45, b)
            grad.setColorAt(1.0, QColor(c.red(), c.green(), c.blue(), 0))
            p.fillRect(area, grad)

    def _paint_key(self, p: QPainter, rect: QRectF, meta: dict, colour: Rgb,
                   radius: float, scale: float) -> None:
        led = meta["id"]
        lit = max(colour) >= 12
        c = QColor(*colour)

        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)

        if lit:
            grad = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            grad.setColorAt(0.0, QColor(c).lighter(150))
            grad.setColorAt(0.5, QColor(c).lighter(108))
            grad.setColorAt(0.52, QColor(c))
            grad.setColorAt(1.0, QColor(c).darker(165))
            p.fillPath(path, grad)
        else:
            grad = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            grad.setColorAt(0.0, QColor("#26333f"))
            grad.setColorAt(1.0, QColor("#18222c"))
            p.fillPath(path, grad)

        # A hairline along the top edge reads as a bevel and stops the keys looking
        # like flat swatches.
        p.setPen(QPen(QColor(255, 255, 255, 40 if lit else 20), max(1.0, scale)))
        p.drawLine(rect.topLeft() + QPointF(radius, 1),
                   rect.topRight() + QPointF(-radius, 1))

        border = QColor(255, 255, 255, 22)
        if led == self._hover:
            border = QColor(255, 255, 255, 120)
        p.setPen(QPen(border, max(1.0, scale)))
        p.drawPath(path)

        if led in self.selection:
            p.setPen(QPen(QColor(255, 255, 255, 235), max(1.6, 2 * scale)))
            p.drawPath(path)
            halo = QPainterPath()
            halo.addRoundedRect(rect.adjusted(-2.5, -2.5, 2.5, 2.5),
                                radius + 2, radius + 2)
            p.setPen(QPen(QColor(255, 255, 255, 70), max(1.0, scale)))
            p.drawPath(halo)

        label = meta["label"] or meta["hex"]
        label = {"CAPSLOCK": "CAPS", "BACKSPACE": "BACK", "LSHIFT": "SHIFT",
                 "RSHIFT": "SHIFT", "LCTRL": "CTRL", "RCTRL": "CTRL",
                 "LALT": "ALT", "RALT": "ALT", "WINLOCK": "LOCK"}.get(label, label)
        font = theme.ui_font(max(6, int(8 * scale)), theme.QFont.Weight.DemiBold)
        if not meta["named"]:
            font = theme.mono_font(max(5, int(7 * scale)))
        p.setFont(font)
        # Dark text on a bright key, light text on a dark one.
        luma = (0.299 * colour[0] + 0.587 * colour[1] + 0.114 * colour[2]) / 255.0
        p.setPen(QColor(0, 0, 0, 205) if lit and luma > 0.55
                 else QColor(255, 255, 255, 235 if lit else 180))
        p.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), label)

    # --- interaction -------------------------------------------------------
    def mousePressEvent(self, event) -> None:
        led = self._at(event.position())
        mods = event.modifiers()
        if led is None:
            if not (mods & (Qt.KeyboardModifier.ShiftModifier
                            | Qt.KeyboardModifier.ControlModifier)):
                self.clear_selection()
            return
        if mods & Qt.KeyboardModifier.ControlModifier:
            self._drag_mode = "remove"
        elif mods & Qt.KeyboardModifier.ShiftModifier:
            self._drag_mode = "add"
        else:
            self._drag_mode = "set"
            self.selection = set()
        self._dragged = set()
        self._apply_drag(led)

    def mouseMoveEvent(self, event) -> None:
        led = self._at(event.position())
        if led != self._hover:
            self._hover = led
            self.update()
        if self._drag_mode and led is not None and led not in self._dragged:
            self._apply_drag(led)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_mode = None
        self._dragged = set()

    def mouseDoubleClickEvent(self, event) -> None:
        led = self._at(event.position())
        if led is not None:
            self.keyActivated.emit(led)

    def leaveEvent(self, event) -> None:
        self._hover = None
        self.update()

    def _apply_drag(self, led: int) -> None:
        self._dragged.add(led)
        if self._drag_mode == "remove":
            self.selection.discard(led)
        else:
            self.selection.add(led)
        self.selectionChanged.emit(set(self.selection))
        self.update()
