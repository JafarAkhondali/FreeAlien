"""Vector-drawn runner view and small, separate persistent score store."""
import os
from pathlib import Path

from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QWidget

from . import theme


def score_path():
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "awcfree/trex-score"


def load_score():
    try:
        return max(0, int(score_path().read_text()))
    except (OSError, ValueError):
        return 0


def save_score(score):
    try:
        path = score_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(max(score, load_score())))
    except OSError:
        pass  # The game remains playable when settings are read-only.


class TrexView(QWidget):
    def __init__(self, game, parent=None):
        super().__init__(parent)
        self.game = game
        self.setMinimumSize(600, 240)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def paintEvent(self, event):
        g = self.game
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#101927" if g.night else "#f4f1e8"))
        p.translate(0, (self.height() - self.width() * 240 / 900) / 2)
        p.scale(self.width() / 900, self.width() / 900)
        ink = QColor("#d8e7e5" if g.night else "#344a46")
        p.setPen(ink)
        p.setFont(theme.mono_font(12))
        p.drawText(QRectF(20, 14, 860, 25), int(Qt.AlignmentFlag.AlignRight),
                   f"HI {g.high_score:05d}   {g.score:05d}")
        p.setPen(QColor("#607479" if g.night else "#b1bcb6"))
        for i in range(5):
            x = (i * 213 - g.distance * .15) % 1000 - 50
            p.drawLine(int(x), 70 + i % 3 * 15, int(x + 38), 70 + i % 3 * 15)
        if g.night:
            p.setBrush(ink)
            p.drawEllipse(QRectF(60, 30, 18, 18))
            for x, y in ((230, 35), (420, 60), (650, 30), (780, 80)):
                p.fillRect(QRectF(x, y, 3, 3), ink)
        p.setPen(ink)
        p.drawLine(0, 201, 900, 201)
        for i in range(24):
            x = (i * 43 - g.distance) % 950 - 25
            p.drawLine(int(x), 211 + i % 3 * 5, int(x + 6), 211 + i % 3 * 5)
        def block(x, y, w, h, colour=ink):
            p.fillRect(QRectF(x, y, w, h), colour)
        for o in g.obstacles:
            top = 200 - o.bottom - o.height
            if o.kind == "bird":
                block(o.x, top + 10, o.width, 9)
                block(o.x + 15, top + (0 if int(g.elapsed * 8) % 2 else 15), 10, 10)
                block(o.x, top + 6, 10, 8)
            else:
                count = 2 if o.width >= 48 else 1
                width = o.width / count
                for n in range(count):
                    cx = o.x + n * width
                    block(cx + width * .35, top, width * .3, o.height)
                    block(cx, top + 10, width, 8)
                    block(cx, top + 4, 5, 14)
                    block(cx + width - 5, top + 6, 5, 12)
        x, y, w, h = g.player_box
        top = 200 - y - h
        colour = QColor("#e05656") if g.state == "over" else ink
        block(x + 7, top + h * .4, w - 12, h * .4, colour)
        block(x + w - 18, top, 22, h * .5, colour)
        block(x, top + h * .3, 9, h * .35, colour)
        foot = 5 if g.y == 0 and g.state == "running" and int(g.elapsed * 12) % 2 else 0
        block(x + 9, top + h * .75, 6, h * .25 - foot, colour)
        block(x + 22, top + h * .75, 6, h * .25 - (5 - foot), colour)
        block(x + w - 3, top + 5, 3, 3, QColor("#f4f1e8"))
        if g.state != "running":
            p.setPen(ink)
            p.setFont(theme.mono_font(18, theme.QFont.Weight.Bold))
            title = {"ready": "T-REX RUN", "paused": "PAUSED", "over": "GAME OVER"}[g.state]
            p.drawText(QRectF(200, 90, 500, 30), int(Qt.AlignmentFlag.AlignCenter), title)
            p.setFont(theme.mono_font(10))
            detail = "P to resume" if g.state == "paused" else "SPACE to run · DOWN to duck"
            p.drawText(QRectF(200, 125, 500, 25), int(Qt.AlignmentFlag.AlignCenter), detail)
        p.end()
