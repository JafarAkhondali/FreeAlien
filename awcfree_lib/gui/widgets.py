"""Custom-painted controls: the colour picker, swatches and chassis zone cards.

Qt's stock colour dialog is a modal box that does not fit a panel you are meant to
keep open while you work, so the picker here is a permanent part of the sidebar: a
saturation/value square with a hue strip under it, both painted directly.
"""
from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient,
)
from PyQt6.QtWidgets import QFrame, QLabel, QSizePolicy, QVBoxLayout, QWidget

from . import theme
from .branding import paint_logo

Rgb = tuple[int, int, int]


class SectionTitle(QLabel):
    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text.upper(), parent)
        self.setObjectName("SectionTitle")
        self.setFont(theme.ui_font(8, theme.QFont.Weight.Bold))


class Panel(QFrame):
    """A rounded translucent card, used for every grouping in the sidebar."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Panel")
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(14, 12, 14, 14)
        self.box.setSpacing(9)

    def add_title(self, text: str) -> None:
        self.box.addWidget(SectionTitle(text))


class SVField(QWidget):
    """Saturation across, value down, for the current hue."""

    changed = pyqtSignal(float, float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.hue = 0.62
        self.sat = 0.7
        self.val = 1.0
        self.setMinimumHeight(170)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def set_hsv(self, h: float, s: float, v: float) -> None:
        self.hue, self.sat, self.val = h, s, v
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, theme.RADIUS_SM, theme.RADIUS_SM)
        p.setClipPath(path)

        base = QColor.fromHsvF(self.hue, 1.0, 1.0)
        white = QLinearGradient(r.topLeft(), r.topRight())
        white.setColorAt(0.0, QColor(255, 255, 255))
        white.setColorAt(1.0, base)
        p.fillRect(r, white)

        dark = QLinearGradient(r.topLeft(), r.bottomLeft())
        dark.setColorAt(0.0, QColor(0, 0, 0, 0))
        dark.setColorAt(1.0, QColor(0, 0, 0, 255))
        p.fillRect(r, dark)

        p.setClipping(False)
        p.setPen(QPen(QColor(255, 255, 255, 30), 1))
        p.drawPath(path)

        cx = r.left() + self.sat * r.width()
        cy = r.top() + (1.0 - self.val) * r.height()
        self._marker(p, QPointF(cx, cy))
        p.end()

    @staticmethod
    def _marker(p: QPainter, c: QPointF) -> None:
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(0, 0, 0, 170), 3))
        p.drawEllipse(c, 7, 7)
        p.setPen(QPen(QColor(255, 255, 255), 2))
        p.drawEllipse(c, 7, 7)

    def _pick(self, pos: QPointF) -> None:
        r = QRectF(self.rect())
        self.sat = min(1.0, max(0.0, (pos.x() - r.left()) / max(1.0, r.width())))
        self.val = 1.0 - min(1.0, max(0.0, (pos.y() - r.top()) / max(1.0, r.height())))
        self.changed.emit(self.sat, self.val)
        self.update()

    def mousePressEvent(self, e) -> None:
        self._pick(e.position())

    def mouseMoveEvent(self, e) -> None:
        if e.buttons():
            self._pick(e.position())


class HueBar(QWidget):
    changed = pyqtSignal(float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.hue = 0.62
        self.setFixedHeight(16)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        grad = QLinearGradient(r.topLeft(), r.topRight())
        for i in range(0, 361, 10):
            grad.setColorAt(i / 360.0, QColor.fromHsvF(i / 360.0, 1.0, 1.0))
        path = QPainterPath()
        path.addRoundedRect(r, r.height() / 2, r.height() / 2)
        p.fillPath(path, grad)
        p.setPen(QPen(QColor(255, 255, 255, 30), 1))
        p.drawPath(path)

        x = r.left() + self.hue * r.width()
        p.setPen(QPen(QColor(0, 0, 0, 160), 4))
        p.drawLine(QPointF(x, r.top() + 1), QPointF(x, r.bottom() - 1))
        p.setPen(QPen(QColor(255, 255, 255), 2))
        p.drawLine(QPointF(x, r.top() + 1), QPointF(x, r.bottom() - 1))
        p.end()

    def _pick(self, pos: QPointF) -> None:
        self.hue = min(1.0, max(0.0, pos.x() / max(1.0, self.width())))
        self.changed.emit(self.hue)
        self.update()

    def mousePressEvent(self, e) -> None:
        self._pick(e.position())

    def mouseMoveEvent(self, e) -> None:
        if e.buttons():
            self._pick(e.position())


class Preview(QWidget):
    """A big swatch of the current colour, glowing the way a lit key does."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.colour = QColor("#5b8cff")
        self.setFixedSize(46, 46)

    def set_colour(self, c: QColor) -> None:
        self.colour = c
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(3, 3, -3, -3)
        glow = QColor(self.colour)
        glow.setAlpha(90)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow)
        p.drawRoundedRect(QRectF(self.rect()), 12, 12)
        p.setBrush(self.colour)
        p.drawRoundedRect(r, 9, 9)
        p.setPen(QPen(QColor(255, 255, 255, 45), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r, 9, 9)
        p.end()


class ColourSlot(QWidget):
    """One of the two colours, clickable to make it the one the picker edits.

    Two slots rather than one because several effects genuinely take a pair --
    the dual-colour wave and the mixed pulse on the keyboard, and any chassis morph
    -- and with a single colour the second half of those was being thrown away.
    """

    clicked = pyqtSignal()

    def __init__(self, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.label = label
        self.colour = QColor("#5b8cff")
        self.active = False
        self.setFixedSize(52, 52)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_colour(self, c: QColor) -> None:
        self.colour = QColor(c)
        self.update()

    def set_active(self, on: bool) -> None:
        self.active = on
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        full = QRectF(self.rect())
        r = full.adjusted(5, 5, -5, -5)

        glow = QColor(self.colour); glow.setAlpha(95)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow)
        p.drawRoundedRect(full.adjusted(1, 1, -1, -1), 13, 13)

        p.setBrush(self.colour)
        p.drawRoundedRect(r, 9, 9)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 50), 1))
        p.drawRoundedRect(r, 9, 9)

        if self.active:
            p.setPen(QPen(QColor(255, 255, 255, 235), 2))
            p.drawRoundedRect(full.adjusted(1, 1, -1, -1), 13, 13)

        p.setFont(theme.ui_font(7, theme.QFont.Weight.Bold))
        luma = (0.299 * self.colour.red() + 0.587 * self.colour.green()
                + 0.114 * self.colour.blue()) / 255.0
        p.setPen(QColor(0, 0, 0, 190) if luma > 0.55 else QColor(255, 255, 255, 210))
        p.drawText(r, int(Qt.AlignmentFlag.AlignCenter), self.label)
        p.end()

    def mousePressEvent(self, e) -> None:
        self.clicked.emit()


class Swatches(QWidget):
    """A fixed palette. Faster than the picker for the colours people actually use."""

    picked = pyqtSignal(QColor)

    COLOURS = [
        "#ff0000", "#e65c00", "#d9ad00", "#008f2b", "#007f66",
        "#007fa8", "#004ee0", "#6d20a8", "#c00068",
        "#ffffff", "#8f3900", "#263d8f", "#4c5663", "#000000",
    ]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.cols = 7
        self._rects: list[tuple[QRectF, QColor]] = []
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        # Keep vertical geometry independent of width. Recomputing a fixed height
        # inside resizeEvent can make scroll-area width and scrollbar visibility
        # oscillate on some native Qt styles, recursively delivering resize events.
        self.setFixedHeight(84)

    def _cell(self) -> float:
        gap = 6.0
        return (self.width() - gap * (self.cols - 1)) / self.cols

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        gap = 6.0
        size = self._cell()
        self._rects = []
        for i, name in enumerate(self.COLOURS):
            col, row = i % self.cols, i // self.cols
            r = QRectF(col * (size + gap), row * (size + gap), size, size)
            c = QColor(name)
            self._rects.append((r, c))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(c)
            p.drawRoundedRect(r, 7, 7)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(255, 255, 255, 46), 1))
            p.drawRoundedRect(r, 7, 7)
        p.end()

    def mousePressEvent(self, e) -> None:
        for r, c in self._rects:
            if r.contains(e.position()):
                self.picked.emit(c)
                return


class BrandMark(QWidget):
    """The supplied project logo, shared with the desktop/window icon."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(38, 38)
        self.setAccessibleName("FreeAlien logo")

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        paint_logo(painter, QRectF(self.rect()))
        painter.end()


def touchpad_path(r: QRectF) -> QPainterPath:
    """The touchpad, as a ring.

    On the real machine only the border of the touchpad lights, not its face, so a
    filled rectangle would misrepresent what the zone actually does.
    """
    outer = QPainterPath()
    outer.addRoundedRect(r, 10, 10)
    inner = QPainterPath()
    inset = min(r.width(), r.height()) * 0.09
    inner.addRoundedRect(r.adjusted(inset, inset, -inset, -inset), 7, 7)
    return outer.subtracted(inner)


class ZoneCard(QFrame):
    """One chassis surface, drawn as the thing it actually is.

    A plain colour bar for all three would be easier, but the touchpad, the head on
    the lid and the power button are physically different objects and the panel is
    much faster to read when they look like it.
    """

    clicked = pyqtSignal(int)

    def __init__(self, zone_id: int, name: str, note: str, shape: str = "pad",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.zone_id = zone_id
        self.name = name
        self.note = note
        self.shape = shape
        self.colour = QColor(0, 0, 0)
        self.selected = False
        self.setFixedHeight(112)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_colour(self, rgb: Rgb) -> None:
        self.colour = QColor(*rgb)
        self.update()

    def set_selected(self, on: bool) -> None:
        self.selected = on
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, theme.RADIUS_SM, theme.RADIUS_SM)
        p.fillPath(path, QColor(255, 255, 255, 10))

        lit = self.colour.value() > 10
        art = QRectF(r.left() + 12, r.top() + 12, r.width() - 24, 56)
        self._paint_art(p, art, lit)

        p.setFont(theme.ui_font(9, theme.QFont.Weight.DemiBold))
        p.setPen(theme.INK if self.selected else theme.INK_DIM)
        p.drawText(QRectF(r.left() + 12, art.bottom() + 6, r.width() - 24, 16),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                   self.name)
        p.setFont(theme.ui_font(7))
        p.setPen(theme.INK_FAINT)
        p.drawText(QRectF(r.left() + 12, art.bottom() + 21, r.width() - 24, 14),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                   self.note)

        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 190 if self.selected else 26),
                      2 if self.selected else 1))
        p.drawPath(path)
        p.end()

    def _paint_art(self, p: QPainter, area: QRectF, lit: bool) -> None:
        dark = QColor("#171b24")
        c = self.colour if lit else dark

        if self.shape in ("head", "power"):
            size = min(area.width(), area.height())
            box = QRectF(0, 0, size, size)
            box.moveCenter(area.center())
            if lit:
                glow = QRadialGradient(box.center(), size * .7)
                colour = QColor(self.colour); colour.setAlpha(125)
                glow.setColorAt(0, colour)
                glow.setColorAt(1, QColor(0, 0, 0, 0))
                p.fillRect(area, glow)
            p.setPen(QPen(self.colour if lit else QColor("#3e515e"), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(box.adjusted(1, 1, -1, -1))
            inset = 5 if self.shape == "power" else 2
            paint_logo(p, box.adjusted(inset, inset, -inset, -inset))
            return
        else:
            box = QRectF(area.left() + area.width() * 0.14, area.top() + 3,
                         area.width() * 0.72, area.height() - 6)
            shape = touchpad_path(box)

        if lit:
            # the halo first, so the shape sits inside its own light
            glow = QColor(self.colour)
            centre = shape.boundingRect().center()
            radius = max(shape.boundingRect().width(),
                         shape.boundingRect().height())
            g = QRadialGradient(centre, radius)
            a = QColor(glow); a.setAlpha(110)
            b = QColor(glow); b.setAlpha(34)
            g.setColorAt(0.0, a)
            g.setColorAt(0.5, b)
            g.setColorAt(1.0, QColor(glow.red(), glow.green(), glow.blue(), 0))
            p.setPen(Qt.PenStyle.NoPen)
            p.fillRect(area.adjusted(-6, -6, 6, 6), g)

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c)
        p.drawPath(shape)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 52 if lit else 26), 1))
        p.drawPath(shape)

    def mousePressEvent(self, e) -> None:
        self.clicked.emit(self.zone_id)


class StatusChip(QWidget):
    """Device-present indicator in the header."""

    def __init__(self, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.label = label
        self.ok = False
        self.setToolTip(f"{label}: connecting…")
        self.setFixedHeight(28)
        self.setFixedWidth(126)

    def set_ok(self, ok: bool) -> None:
        self.ok = ok
        self.setToolTip(f"{self.label}: {'connected' if ok else 'unavailable'}")
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(QColor(255, 255, 255, 26), 1))
        p.setBrush(QColor(255, 255, 255, 10))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)

        dot = theme.OK if self.ok else theme.DANGER
        halo = QColor(dot); halo.setAlpha(80)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(halo)
        p.drawEllipse(QPointF(r.left() + 14, r.center().y()), 7, 7)
        p.setBrush(dot)
        p.drawEllipse(QPointF(r.left() + 14, r.center().y()), 3.5, 3.5)

        p.setFont(theme.ui_font(8, theme.QFont.Weight.Medium))
        p.setPen(theme.INK_DIM)
        p.drawText(QRectF(r.left() + 26, r.top(), r.width() - 32, r.height()),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                   self.label)
        p.end()


class PartBar(QWidget):
    """Which part of the machine the panel is currently about.

    A single exclusive choice rather than several independent toggles, because the
    whole point is that only one part's controls are on screen at a time.
    """

    changed = pyqtSignal(str)

    def __init__(self, items: list[tuple[str, str]],
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.items = items
        self.current = items[0][0]
        self._rects: list[tuple[QRectF, str]] = []
        self._hover: str | None = None
        self.setFixedHeight(44)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("Lighting surface")
        self.setToolTip("Choose a surface · use arrow keys when focused")
        self.setMinimumWidth(360)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def select(self, key: str, emit: bool = True) -> None:
        if key == self.current:
            self.update()
            return
        self.current = key
        self.update()
        if emit:
            self.changed.emit(key)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(QColor(255, 255, 255, 22), 1))
        p.setBrush(QColor(255, 255, 255, 10))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)

        if self.hasFocus():
            p.setPen(QPen(theme.ACCENT, 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        pad = 3.0
        inner = r.adjusted(pad, pad, -pad, -pad)
        width = inner.width() / len(self.items)
        self._rects = []
        p.setFont(theme.ui_font(8, theme.QFont.Weight.DemiBold))
        for i, (key, label) in enumerate(self.items):
            cell = QRectF(inner.left() + i * width, inner.top(), width, inner.height())
            self._rects.append((cell, key))
            if key == self.current:
                grad = QLinearGradient(cell.topLeft(), cell.topRight())
                grad.setColorAt(0.0, theme.ACCENT)
                grad.setColorAt(1.0, theme.ACCENT_2)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(grad)
                p.drawRoundedRect(cell, cell.height() / 2, cell.height() / 2)
                p.setPen(QColor("#102820"))
            elif key == self._hover:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(255, 255, 255, 16))
                p.drawRoundedRect(cell, cell.height() / 2, cell.height() / 2)
                p.setPen(theme.INK)
            else:
                p.setPen(theme.INK_DIM)
            p.drawText(cell, int(Qt.AlignmentFlag.AlignCenter), label)
        p.end()

    def keyPressEvent(self, e) -> None:
        keys = [key for key, _ in self.items]
        if e.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Home, Qt.Key.Key_End):
            index = keys.index(self.current)
            if e.key() == Qt.Key.Key_Home:
                index = 0
            elif e.key() == Qt.Key.Key_End:
                index = len(keys) - 1
            else:
                index = (index + (1 if e.key() == Qt.Key.Key_Right else -1)) % len(keys)
            self.select(keys[index])
            e.accept()
        else:
            super().keyPressEvent(e)

    def mousePressEvent(self, e) -> None:
        for cell, key in self._rects:
            if cell.contains(e.position()):
                self.select(key)
                return

    def mouseMoveEvent(self, e) -> None:
        hit = None
        for cell, key in self._rects:
            if cell.contains(e.position()):
                hit = key
                break
        if hit != self._hover:
            self._hover = hit
            self.update()

    def leaveEvent(self, e) -> None:
        self._hover = None
        self.update()
