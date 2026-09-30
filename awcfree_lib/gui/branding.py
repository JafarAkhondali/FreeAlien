"""Shared branding from the supplied artwork, preserved at its original resolution."""
from functools import lru_cache
from pathlib import Path

from PyQt6.QtCore import QRectF
from PyQt6.QtGui import QIcon, QPainter, QPixmap

LOGO_PATH = Path(__file__).with_name('assets') / 'logo.png'


@lru_cache(maxsize=1)
def logo_pixmap():
    # Called only after QApplication exists; retain source resolution for HiDPI.
    return QPixmap(str(LOGO_PATH))


def app_icon():
    return QIcon(str(LOGO_PATH))


def paint_logo(painter, area):
    pixmap = logo_pixmap()
    if pixmap.isNull():
        return
    scale = min(area.width() / pixmap.width(), area.height() / pixmap.height())
    target = QRectF(0, 0, pixmap.width() * scale, pixmap.height() * scale)
    target.moveCenter(area.center())
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    painter.drawPixmap(target, pixmap, QRectF(pixmap.rect()))
    painter.restore()
