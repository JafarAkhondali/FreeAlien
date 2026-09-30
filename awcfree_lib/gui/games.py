"""LED-backed arcade page for Snake, Minesweeper, Zombie Defense and T-Rex."""
from __future__ import annotations

import random
import time
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QRectF, QEvent
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                             QSlider, QCheckBox, QSizePolicy, QApplication)

from .. import layout as kb_layout
from ..canvas import Canvas
from ..games.snake import SnakeGame, Field
from ..games.minesweeper import Minesweeper, COUNT_COLOURS
from ..games.defense import DefenseGame
from ..games.trex import TrexGame
from .trex import TrexView, load_score, save_score
from ..games.audio import ArcadeAudio
from . import theme
from .widgets import Panel, SectionTitle

FIELD = Field(2, 1, 10, 4)
assert FIELD.cells <= set(kb_layout.CELLS.values()), "game board must map to real keys"
FIELD_LEDS = {pos: led for led, pos in kb_layout.CELLS.items() if pos in FIELD.cells}
FIELD_NAMES = {pos: kb_layout.NAMES.get(led, "") for pos, led in FIELD_LEDS.items()}
DEFENSE_FIELD = Field(0, min(DefenseGame.LANES), kb_layout.GRID_COLS,
                      max(DefenseGame.LANES) - min(DefenseGame.LANES) + 1)
DEFENSE_LEDS = {pos: led for led, pos in kb_layout.CELLS.items()
                if pos in DEFENSE_FIELD.cells}
DEFENSE_NAMES = {pos: kb_layout.NAMES.get(led, "") for pos, led in DEFENSE_LEDS.items()}


class GameBoard(QWidget):
    cellClicked = pyqtSignal(tuple, bool)
    keyPressed = pyqtSignal(int, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.field = FIELD
        self.colours: dict[tuple[int, int], tuple[int, int, int]] = {}
        self.labels: dict[tuple[int, int], str] = FIELD_NAMES
        self.cursor: tuple[int, int] | None = None
        self.banner = ""
        self.banner_detail = ""
        self.banner_colour = (255, 255, 255)
        self.banner_frame = 0
        self.banner_timer = QTimer(self)
        self.banner_timer.setInterval(30)
        self.banner_timer.timeout.connect(self._advance_banner)
        self.setMinimumSize(600, 300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def set_frame(self, colours, labels=None, cursor=None):
        self.colours = dict(colours)
        if labels is not None:
            self.labels = dict(labels)
        self.cursor = cursor
        self.update()

    def _cell_rect(self, cell):
        cw = self.width() / self.field.width
        ch = self.height() / self.field.height
        x, y = cell
        return QRectF((x - self.field.x0) * cw + 3, (y - self.field.y0) * ch + 3, cw - 6, ch - 6)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor("#0b1118"))
        for cell in sorted(self.field.cells, key=lambda c: (c[1], c[0])):
            rect = self._cell_rect(cell)
            rgb = self.colours.get(cell, (24, 34, 45))
            c = QColor(*rgb)
            p.setPen(QPen(QColor("#34424e"), 1))
            p.setBrush(c)
            p.drawRoundedRect(rect, 7, 7)
            label = self.labels.get(cell, "")
            # Mines board labels come from game state; snake retains real key caps.
            if label:
                p.setPen(QColor("#e7edf5"))
                p.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), label)
            if cell == self.cursor:
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(QColor("#f5c842"), 3))
                p.drawRoundedRect(rect.adjusted(2, 2, -2, -2), 6, 6)
        if self.banner:
            progress = min(1.0, self.banner_frame / 28)
            fade = min(1.0, progress * 5, (1.0 - progress) * 3 + 0.15)
            alpha = max(0, min(205, int(190 * fade)))
            shade = QColor("#060a10")
            shade.setAlpha(alpha)
            p.fillRect(self.rect(), shade)
            card = QRectF(self.width() * .17, self.height() * .27,
                          self.width() * .66, self.height() * .46)
            p.setPen(QPen(QColor(*self.banner_colour), 2))
            p.setBrush(QColor("#101923"))
            p.drawRoundedRect(card, 18, 18)
            title_colour = QColor(*self.banner_colour)
            title_colour.setAlpha(max(0, min(255, int(255 * fade))))
            p.setPen(title_colour)
            p.setFont(theme.ui_font(max(18, int(self.height() * .11)), theme.QFont.Weight.Bold))
            p.drawText(QRectF(card.left() + 10, card.top() + 8, card.width() - 20,
                              card.height() * .58), int(Qt.AlignmentFlag.AlignCenter), self.banner)
            detail_colour = QColor("#e8ecf6")
            detail_colour.setAlpha(max(0, min(230, int(230 * fade))))
            p.setPen(detail_colour)
            p.setFont(theme.ui_font(max(9, int(self.height() * .035))))
            p.drawText(QRectF(card.left() + 12, card.top() + card.height() * .58,
                              card.width() - 24, card.height() * .30),
                       int(Qt.AlignmentFlag.AlignCenter), self.banner_detail)
        p.end()

    def announce(self, title, detail, colour):
        self.banner = title
        self.banner_detail = detail
        self.banner_colour = colour
        self.banner_frame = 0
        self.banner_timer.start()
        self.update()

    def _advance_banner(self):
        self.banner_frame += 1
        if self.banner_frame >= 34:
            self.banner = ""
            self.banner_timer.stop()
        self.update()

    def mousePressEvent(self, event):
        self.setFocus()
        cw, ch = self.width() / self.field.width, self.height() / self.field.height
        cell = (self.field.x0 + int(event.position().x() / cw),
                self.field.y0 + int(event.position().y() / ch))
        if cell in self.field.cells:
            self.cellClicked.emit(cell, event.button() == Qt.MouseButton.RightButton)

    def keyPressEvent(self, event):
        self.keyPressed.emit(event.key(), event.modifiers())
        event.accept()


class GamesPage(QWidget):
    """Runs animation from a Qt timer and sends only the selected measured region."""
    def __init__(self, hardware, get_base_colours, restore_colours, parent=None):
        super().__init__(parent)
        self.hw = hardware
        self.get_base_colours = get_base_colours
        self.restore_colours = restore_colours
        self.mode = "snake"
        self.running = False
        self.applied = False
        self.snake = SnakeGame(FIELD)
        self.mines = Minesweeper(FIELD)
        self.defense = DefenseGame()
        self.trex = TrexGame(high_score=load_score())
        self.trex_held = set()
        self.audio = ArcadeAudio()
        self.defense_state = "ready"
        self.defense_held: dict[int, float] = {}
        self.active_leds = FIELD_LEDS
        self.active_names = FIELD_NAMES
        self.mine_state = "ready"
        self._last_mines_result = None
        self.mine_cursor = (FIELD.x0 + FIELD.width // 2,
                            FIELD.y0 + FIELD.height // 2)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)
        head = QHBoxLayout()
        text = QVBoxLayout()
        text.addWidget(SectionTitle("ARCADE · MEASURED LED FIELD"))
        self.title = QLabel("Snake")
        self.title.setObjectName("StageTitle")
        text.addWidget(self.title)
        head.addLayout(text)
        head.addStretch()
        self.game_pick = QHBoxLayout()
        self.snake_btn = QPushButton("Snake")
        self.mines_btn = QPushButton("Minesweeper")
        self.defense_btn = QPushButton("Zombie Defense")
        self.trex_btn = QPushButton("T-Rex")
        for b, mode in ((self.snake_btn, "snake"), (self.mines_btn, "mines"),
                        (self.defense_btn, "defense"), (self.trex_btn, "trex")):
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, m=mode: self.set_mode(m))
            self.game_pick.addWidget(b)
        head.addLayout(self.game_pick)
        root.addLayout(head)

        board_panel = Panel()
        self.board_heading = SectionTitle("10 × 4 contiguous key block · number row through Win–/")
        board_panel.box.addWidget(self.board_heading)
        self.board = GameBoard()
        self.board.cellClicked.connect(self._mine_click)
        self.board.keyPressed.connect(self._handle_mines_key)
        board_panel.box.addWidget(self.board, 1)
        self.trex_view = TrexView(self.trex)
        board_panel.box.addWidget(self.trex_view, 1)
        root.addWidget(board_panel, 1)

        controls = Panel()
        controls.add_title("Game controls")
        row = QHBoxLayout()
        self.start_btn = QPushButton("Start")
        self.start_btn.setProperty("accent", "true")
        self.start_btn.clicked.connect(self.toggle_run)
        restart = QPushButton("Restart")
        restart.clicked.connect(self.restart)
        row.addWidget(self.start_btn)
        row.addWidget(restart)
        row.addSpacing(12)
        row.addWidget(QLabel("Speed"))
        self.speed = QSlider(Qt.Orientation.Horizontal)
        self.speed.setRange(2, 14)
        self.speed.setValue(6)
        self.speed.setFixedWidth(130)
        self.speed.valueChanged.connect(self._retime)
        row.addWidget(self.speed)
        self.wrap = QCheckBox("Wrap edges")
        self.wrap.setChecked(True)
        self.wrap.toggled.connect(self._wrap_changed)
        row.addWidget(self.wrap)
        row.addWidget(QLabel("Mines"))
        self.mine_count = QSlider(Qt.Orientation.Horizontal)
        self.mine_count.setRange(5, 18)
        self.mine_count.setValue(8)
        self.mine_count.setFixedWidth(110)
        self.mine_count.valueChanged.connect(self._new_mines)
        self.charge = QSlider(Qt.Orientation.Horizontal)
        self.charge.setRange(0, 100)
        self.charge.setValue(0)
        self.charge.setEnabled(False)
        row.addWidget(self.mine_count)
        self.charge_label = QLabel("Charge")
        row.addWidget(self.charge_label)
        row.addWidget(self.charge)
        row.addStretch()
        self.status = QLabel("Arrows / WASD to steer · Space to pause")
        self.status.setObjectName("Hint")
        self.status.setWordWrap(True)
        row.addWidget(self.status)
        controls.box.addLayout(row)
        root.addWidget(controls)

        self.legend_panel = Panel()
        self.legend_panel.add_title("Minesweeper · number of neighbouring mines")
        legendrow = QHBoxLayout()
        self.legend = QLabel("F1 1 · red     F2 2 · orange     F3 3 · yellow     F4 4 · green     F5 5 · blue     F6 6 · violet\nFlag the shown count, then press the numbered key again to reveal its neighbours")
        self.legend.setFont(theme.mono_font(9, theme.QFont.Weight.DemiBold))
        self.legend.setWordWrap(True)
        legendrow.addWidget(self.legend)
        legendrow.addStretch()
        self.legend_panel.box.addLayout(legendrow)
        root.addWidget(self.legend_panel)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self._mines_labels = {}
        self.game_pick.setContentsMargins(0, 0, 0, 0)
        self.set_mode("snake")

    def _retime(self, value):
        if self.running and self.mode == "snake":
            self.timer.setInterval(int(1000 / value))

    def _wrap_changed(self, checked):
        self.snake.field = Field(FIELD.x0, FIELD.y0, FIELD.width, FIELD.height,
                                 FIELD.walls, checked)
        self.snake.reset()
        if self.mode == "snake": self._draw_snake()

    def _new_mines(self, value):
        if hasattr(self, "mines"):
            self.mines = Minesweeper(FIELD, value)
            self.mine_state = "ready"
            self.start_btn.setText("Start game")
            if self.mode == "mines": self._draw_mines()

    def set_mode(self, mode):
        self.stop(restore=True)
        self.mode = mode
        self.snake_btn.setChecked(mode == "snake")
        self.mines_btn.setChecked(mode == "mines")
        self.defense_btn.setChecked(mode == "defense")
        self.trex_btn.setChecked(mode == "trex")
        self.trex_view.setVisible(mode == "trex")
        self.board.setVisible(mode != "trex")
        self.active_leds = DEFENSE_LEDS if mode == "defense" else FIELD_LEDS
        self.active_names = DEFENSE_NAMES if mode == "defense" else FIELD_NAMES
        self.board.field = DEFENSE_FIELD if mode == "defense" else FIELD
        self.board.labels = self.active_names
        self.board_heading.setText("Three keyboard rows · Tab / Caps Lock / Left Shift defend their lanes"
                                   if mode == "defense" else
                                   "10 × 4 contiguous key block · number row through Win–/")
        if mode == "trex":
            self.board_heading.setText("Offline runner · green dinosaur / red cacti / amber birds on the keyboard")
        self.wrap.setVisible(mode == "snake")
        self.speed.setVisible(mode == "snake")
        self.mine_count.setVisible(mode == "mines")
        self.legend_panel.setVisible(mode == "mines")
        self.charge.setVisible(mode == "defense")
        self.charge_label.setVisible(mode == "defense")
        for child in self.findChildren(QLabel):
            if child.text() == "Speed": child.setVisible(mode == "snake")
            elif child.text() == "Mines": child.setVisible(mode == "mines")
        self.title.setText({"snake": "Snake", "mines": "Minesweeper",
                            "defense": "Zombie Defense", "trex": "T-Rex"}[mode])
        self.status.setText({"snake": "Ready · Start to play · Arrows / WASD steer · Space pauses",
                             "mines": "READY · press a board key to reveal it · Ctrl+key flags · arrows move",
                             "defense": "READY · Start, then hold/release Tab, Caps Lock or Left Shift to fire",
                             "trex": "Space / ↑ jump · ↓ duck · P pause · R restart"}[mode])
        self.start_btn.setText("Start" if mode == "snake" else "Start game")
        self.mine_state = "ready"
        self.defense_state = "ready"
        self.defense_held.clear()
        self.charge.setValue(0)
        if mode == "mines":
            self.mines = Minesweeper(FIELD, self.mine_count.value())
        self.mine_cursor = (FIELD.x0 + FIELD.width // 2,
                            FIELD.y0 + FIELD.height // 2)
        self._refresh()
        if mode == "mines" and self.isVisible():
            self.board.setFocus()

    def toggle_run(self):
        if self.mode == "trex":
            if self.trex.state == "running":
                self.stop()
            else:
                self.trex.start()
                self.running = True
                self._trex_last = time.monotonic()
                self.timer.start(33)
                self.trex_view.setFocus()
            self._draw_trex(send=self.running)
            return
        if self.mode == "mines":
            if self.mine_state == "playing":
                self._end_mines_round()
            else:
                self._begin_mines_round()
            return
        if self.mode == "defense":
            if self.defense_state == "playing":
                self._end_defense("ended")
            else:
                self._begin_defense()
            return
        if self.running:
            self.stop(restore=True)
        else:
            self.running = True
            self.start_btn.setText("Pause")
            self.setFocus()
            self._render_snake()
            self.timer.start(int(1000 / self.speed.value()))

    def stop(self, restore=True):
        if self.mode == "trex":
            self.trex.pause()
            self.trex_held.clear()
            save_score(self.trex.high_score)
            self.trex_view.update()
        self.running = False
        self.timer.stop()
        self.defense_held.clear()
        if hasattr(self, "start_btn"):
            self.start_btn.setText("Start" if self.mode == "snake" else
                                   "End game" if self.mine_state == "playing" else
                                   "End game" if self.mode == "defense" and self.defense_state == "playing" else
                                   "Start game")
        if self.mode == "trex":
            self.start_btn.setText("Resume" if self.trex.state == "paused" else "Play again")
        if restore and self.applied:
            self.restore_colours()
            self.applied = False

    def _begin_mines_round(self):
        self.mines = Minesweeper(FIELD, self.mine_count.value())
        self.mine_state = "playing"
        self._last_mines_result = None
        self.start_btn.setText("End game")
        self.mine_cursor = (FIELD.x0 + FIELD.width // 2,
                            FIELD.y0 + FIELD.height // 2)
        self._draw_mines()
        self.board.setFocus()
        self.board.announce("READY", "Press a key to reveal · Ctrl + key to flag",
                            (255, 190, 0))
        QTimer.singleShot(420, self._announce_go)

    def _announce_go(self):
        if self.mode == "mines" and self.mine_state == "playing":
            self.board.announce("GO!", "Your keyboard is the board",
                                (0, 210, 105))

    def restart(self):
        self.stop(restore=True)
        if self.mode == "trex":
            self.trex.reset()
            self.toggle_run()
        elif self.mode == "snake":
            self.snake.reset()
            self._draw_snake()
        elif self.mode == "mines":
            self.mines = Minesweeper(FIELD, self.mine_count.value())
            self.mine_state = "ready"
            self._last_mines_result = None
            self.start_btn.setText("Start game")
            self._draw_mines()
        else:
            self.defense.reset()
            self.defense_state = "ready"
            self.start_btn.setText("Start game")
            self._draw_defense()

    def _refresh(self):
        if self.mode == "trex": self._draw_trex()
        elif self.mode == "snake": self._draw_snake()
        elif self.mode == "mines": self._draw_mines()
        else: self._draw_defense()

    def _base_frame(self):
        frame = dict(self.get_base_colours())
        ui = {}
        for cell, led in self.active_leds.items():
            ui[cell] = frame.get(led, (0, 0, 0))
        return frame, ui

    def _send(self, cell_colours):
        frame, ui = self._base_frame()
        for cell, rgb in cell_colours.items():
            ui[cell] = rgb
            led = self.active_leds[cell]
            frame[led] = rgb
        # The measured function-key row doubles as a permanent, physical legend.
        for n, rgb in COUNT_COLOURS.items():
            if self.mode == "mines" and n <= 6:
                led = kb_layout.by_name(f"F{n}")
                frame[led] = rgb
        self.board.set_frame(ui, cursor=self.mine_cursor if self.mode == "mines" else None)
        if self.isVisible():
            self.hw.submit("keyboard", self.hw.write_keys, frame)
            self.applied = True

    def enter(self):
        self._refresh()

    def _draw_snake(self):
        self._render_snake()

    def _render_snake(self):
        canvas = Canvas(background=(12, 18, 25))
        self.snake.render(canvas, head=(255, 255, 255), body=(0, 185, 52),
                          tail=(0, 45, 16), food=(255, 0, 0))
        all_colours = canvas.to_leds()
        colours = {cell: all_colours.get(led, (0, 0, 0))
                   for cell, led in FIELD_LEDS.items()}
        self._send(colours)
        self.status.setText(f"Score {self.snake.score} · Arrows / WASD to steer · Space to pause")

    def _tick(self):
        if self.mode == "trex":
            now = time.monotonic()
            for sound in self.trex.step(now - self._trex_last):
                self.audio.play(sound)
            self._trex_last = now
            if self.trex.state == "over":
                self.stop(restore=False)
            self._draw_trex()
            return
        if self.mode == "defense":
            self._defense_tick()
            return
        if not self.snake.step():
            self._render_snake()
            self.stop(restore=False)
            self.status.setText("Game over · Restart for another round")
            return
        self._render_snake()

    def _mine_click(self, cell, right):
        if self.mode != "mines": return
        if self.mine_state != "playing":
            self.status.setText("READY · Press Start game before making a move")
            return
        self.mine_cursor = cell
        if right: self.mines.toggle_flag(cell)
        else:
            self._reveal_mines_cell(cell)
            return
        self._draw_mines()

    def _reveal_mines_cell(self, cell):
        if cell in self.mines.revealed:
            count = self.mines.count(cell)
            flagged = len(self.mines.neighbours(cell) & self.mines.flags)
            if count == 0:
                self.status.setText("BLANK KEY · its neighbouring keys are already clear")
                return
            if flagged != count:
                needed = count - flagged
                message = (f"NUMBER {count} · Flag {needed} more neighbouring mine"
                           f"{'s' if needed != 1 else ''}, then press this key again"
                           if needed > 0 else
                           f"NUMBER {count} · Remove {abs(needed)} extra flag"
                           f"{'s' if abs(needed) != 1 else ''}, then press this key again")
                self.status.setText(message)
                return
        self.mines.reveal(cell)
        self._draw_mines()

    def _end_mines_round(self):
        self.mine_state = "ended"
        self.start_btn.setText("Start game")
        self.status.setText("ROUND ENDED · Press Start game for a fresh board")
        self._draw_mines()
        self.board.announce("ROUND OVER", "Press a key to start again", (255, 170, 0))

    @staticmethod
    def _key_cells():
        keys = {}
        named = {"-": Qt.Key.Key_Minus, "=": Qt.Key.Key_Equal,
                 "[": Qt.Key.Key_BracketLeft, "]": Qt.Key.Key_BracketRight,
                 "\\": Qt.Key.Key_Backslash, ";": Qt.Key.Key_Semicolon,
                 "'": Qt.Key.Key_Apostrophe, ",": Qt.Key.Key_Comma,
                 ".": Qt.Key.Key_Period, "/": Qt.Key.Key_Slash}
        for digit in "0123456789":
            named[digit] = getattr(Qt.Key, f"Key_{digit}")
        for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            named[letter] = getattr(Qt.Key, f"Key_{letter}")
        for cell, label in FIELD_NAMES.items():
            if label in named:
                keys[named[label]] = cell
        return keys

    def _handle_mines_key(self, key, modifiers):
        if self.mode != "mines":
            return False
        ctrl = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
        key_cells = self._key_cells()
        if self.mine_state != "playing":
            if key == Qt.Key.Key_Escape:
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
                self._begin_mines_round()
                return True
            if key in key_cells:
                self._begin_mines_round()
                if ctrl:
                    self.mines.toggle_flag(key_cells[key])
                else:
                    self.mine_cursor = key_cells[key]
                    self.mines.reveal(self.mine_cursor)
                self._draw_mines()
                return True
            return False
        if ctrl:
            if key == Qt.Key.Key_Space or key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.mines.toggle_flag(self.mine_cursor)
            else:
                target = key_cells.get(key)
                if target is not None:
                    self.mine_cursor = target
                    self.mines.toggle_flag(target)
                else:
                    return False
            self._draw_mines()
            return True
        directions = {
            Qt.Key.Key_Up: (0, -1), Qt.Key.Key_Down: (0, 1),
            Qt.Key.Key_Left: (-1, 0), Qt.Key.Key_Right: (1, 0),
        }
        if key in directions:
            dx, dy = directions[key]
            x, y = self.mine_cursor
            self.mine_cursor = (min(FIELD.x0 + FIELD.width - 1, max(FIELD.x0, x + dx)),
                                min(FIELD.y0 + FIELD.height - 1, max(FIELD.y0, y + dy)))
            self._draw_mines()
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self._reveal_mines_cell(self.mine_cursor)
        elif key == Qt.Key.Key_Escape:
            self._end_mines_round()
        elif key in key_cells:
            # Physical key presses address the matching measured key directly.
            # Ctrl+key follows the same map to place/remove a flag.
            self.mine_cursor = key_cells[key]
            self._reveal_mines_cell(self.mine_cursor)
        else:
            return False
        return True

    def _draw_mines(self):
        labels = dict(FIELD_NAMES)
        colours = {}
        for cell in FIELD.cells:
            if cell in self.mines.flags:
                colours[cell] = (255, 60, 0); labels[cell] = "⚑"
            elif cell in self.mines.mines and (self.mines.over or self.mine_state == "ended"):
                colours[cell] = (255, 0, 0) if cell == self.mines.exploded else (120, 0, 0)
                labels[cell] = "✹"
            elif cell not in self.mines.revealed:
                colours[cell] = (26, 39, 52)
                labels[cell] = FIELD_NAMES.get(cell, "")
            elif cell in self.mines.mines:
                colours[cell] = (180, 0, 0); labels[cell] = "✹"
            else:
                n = self.mines.count(cell)
                colours[cell] = COUNT_COLOURS.get(n, (35, 45, 55)) if n else (20, 35, 43)
                labels[cell] = str(n) if n else "·"
        if self.mines.over:
            self.mine_state = "won" if self.mines.won else "lost"
            self.start_btn.setText("Play again")
            self.status.setText("VICTORY · all safe keys cleared · press Play again" if self.mines.won else
                                "MINE HIT · round over · press Play again")
            result = self.mine_state
            if result != self._last_mines_result:
                self.board.announce("YOU WIN!" if self.mines.won else "MINE HIT",
                                    "Board cleared" if self.mines.won else "Round over",
                                    (0, 220, 100) if self.mines.won else (255, 0, 0))
                self._last_mines_result = result
        elif self.mine_state == "ended":
            self.status.setText("ROUND ENDED · Press Start game for a fresh board")
        elif self.mine_state == "ready":
            self.status.setText(f"READY · {self.mine_count.value()} mines · Press Start game")
        else:
            key_name = FIELD_NAMES.get(self.mine_cursor, "key")
            self.status.setText(f"PLAYING · {len(self.mines.flags)}/{self.mine_count.value()} flagged · cursor {key_name} · press key reveals its square · Ctrl+key flags · arrows move · Esc ends")
        self._mines_labels = labels
        self.board.labels = labels
        self._send(colours)

    def keyPressEvent(self, event):
        if self.mode == "mines":
            self._handle_mines_key(event.key(), event.modifiers())
            return
        else:
            directions = {Qt.Key.Key_Up: "up", Qt.Key.Key_W: "up",
                          Qt.Key.Key_Down: "down", Qt.Key.Key_S: "down",
                          Qt.Key.Key_Left: "left", Qt.Key.Key_A: "left",
                          Qt.Key.Key_Right: "right", Qt.Key.Key_D: "right"}
            if event.key() in directions:
                self.snake.turn(directions[event.key()]); return
            if event.key() == Qt.Key.Key_Space:
                self.toggle_run(); return
        super().keyPressEvent(event)

    def eventFilter(self, watched, event):
        if self.mode == "trex" and self.isVisible():
            if event.type() in (QEvent.Type.ApplicationDeactivate, QEvent.Type.WindowDeactivate):
                if self.trex.state == "running":
                    self.stop()
                    self._draw_trex(send=False)
            if (event.type() in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease)
                    and self.window().isActiveWindow()
                    and self._trex_key(event)):
                return True
        if (event.type() in (QEvent.Type.ApplicationDeactivate, QEvent.Type.WindowDeactivate)
                and self.mode == "defense" and self.defense_held):
            self.defense_held.clear()
            self.charge.setValue(0)
        if (event.type() == QEvent.Type.KeyPress and self.isVisible()
                and self.window().isActiveWindow()):
            if (event.modifiers() & Qt.KeyboardModifier.ControlModifier
                    and event.modifiers() & Qt.KeyboardModifier.ShiftModifier
                    and event.key() == Qt.Key.Key_M):
                self.window()._open_mines_from_keyboard()
                return True
            if self.mode == "defense" and self.defense_state == "playing":
                lane = self._defense_lane(event.key(), event.nativeScanCode())
                if lane is not None:
                    if lane not in self.defense_held:
                        self.defense_held[lane] = time.monotonic()
                    return True
            if self.mode == "mines" and self._handle_mines_key(
                    event.key(), event.modifiers()):
                return True
        if (event.type() == QEvent.Type.KeyRelease and self.isVisible()
                and self.window().isActiveWindow() and self.mode == "defense"):
            lane = self._defense_lane(event.key(), event.nativeScanCode())
            if lane is not None and lane in self.defense_held:
                held = max(0.0, time.monotonic() - self.defense_held.pop(lane))
                charge = min(1.0, held / 1.25)
                self.defense.shoot(lane, charge)
                self.audio.play("shot")
                self._draw_defense()
                return True
        return super().eventFilter(watched, event)

    @staticmethod
    def _defense_lane(key, scan_code=0):
        if key == Qt.Key.Key_Tab: return DefenseGame.FIRING_CELLS["TAB"][1]
        if key == Qt.Key.Key_CapsLock: return DefenseGame.FIRING_CELLS["CAPSLOCK"][1]
        if key == Qt.Key.Key_Shift and scan_code in (0, 50):
            return DefenseGame.FIRING_CELLS["LSHIFT"][1]
        return None

    def _begin_defense(self):
        self.defense.reset()
        self.defense_state = "playing"
        self.defense.spawn(DefenseGame.LANES[0], 2)
        self.defense.spawn(DefenseGame.LANES[1], 3)
        self.start_btn.setText("End game")
        self.status.setText("DEFEND · Hold Tab / Caps Lock / Left Shift to charge, release to fire · charged shots splash downward")
        self.board.announce("ZOMBIE DEFENSE", "Hold a firing key to charge · release to shoot",
                            (255, 75, 30))
        self._draw_defense()
        self.timer.start(50)

    def _end_defense(self, result):
        self.defense_state = result
        self.timer.stop()
        self.defense_held.clear()
        self.start_btn.setText("Play again" if result == "lost" else "Start game")
        if result == "lost":
            self.status.setText(f"BREACH · {self.defense.score} eliminated · press Play again")
            self.board.announce("BASE BREACHED", f"{self.defense.score} eliminated",
                                (255, 0, 0))
        else:
            self.status.setText(f"ROUND ENDED · {self.defense.score} eliminated · press Start game")
            self.board.announce("ROUND OVER", "Press Start game for another defense",
                                (255, 150, 0))
        self._draw_defense()

    def _defense_tick(self):
        held = next(iter(self.defense_held.values()), None)
        self.charge.setValue(int(min(1.0, (time.monotonic() - held) / 1.25) * 100)
                             if held is not None else 0)
        sounds = self.defense.step(0.05)
        for sound in sounds:
            self.audio.play(sound)
        self._draw_defense()
        if self.defense.over:
            self._end_defense("lost")

    def _draw_defense(self):
        colours = {cell: (9, 16, 23) for cell in DEFENSE_LEDS}
        labels = dict(DEFENSE_NAMES)
        # The three physical launch keys glow while charging.
        charge = min(1.0, (max((time.monotonic() - t
                                for t in self.defense_held.values()), default=0.0)) / 1.25)
        for cell in DefenseGame.FIRING_CELLS.values():
            colours[cell] = (30 + int(charge * 225), 90 + int(charge * 120), 255)
        for zombie in self.defense.zombies:
            x = max(0, min(15, round(zombie.x)))
            cell = (x, zombie.y)
            if cell in colours:
                brightness = self.defense.health_brightness(zombie)
                colours[cell] = (int(255 * brightness), int(35 * brightness), 8)
                labels[cell] = "Z"
        for bullet in self.defense.bullets:
            cell = (round(bullet.x), bullet.y)
            if cell in colours:
                colours[cell] = (255, 190, 0) if bullet.splash else (0, 210, 255)
        self.board.set_frame(colours, labels=labels)
        frame = dict(self.get_base_colours())
        for cell, rgb in colours.items():
            led = DEFENSE_LEDS.get(cell)
            if led is not None:
                frame[led] = rgb
        if self.isVisible():
            self.hw.submit("keyboard", self.hw.write_keys, frame)
            self.applied = True
        self.status.setText(f"ELIMINATED {self.defense.score} · WAVE {self.defense.wave} · Zombies glow brighter at full health · hold, then release to fire")

    def _draw_trex(self, send=True):
        self.trex_view.update()
        if send:
            self._send(self.trex.led_colours(FIELD))
        self.start_btn.setText({"ready": "Start", "running": "Pause",
                                "paused": "Resume", "over": "Play again"}[self.trex.state])
        self.status.setText(f"{self.trex.state.upper()} · Score {self.trex.score} · Best {self.trex.high_score} · "
                            "White dino = jump now · Space / ↑ jump (hold for height) · ↓ duck / fast fall · P pause · R restart · Esc pause")

    def _trex_key(self, event):
        key = event.key()
        jumps = (Qt.Key.Key_Space, Qt.Key.Key_Up, Qt.Key.Key_W)
        ducks = (Qt.Key.Key_Down, Qt.Key.Key_S)
        controls = jumps + ducks + (Qt.Key.Key_P, Qt.Key.Key_Escape, Qt.Key.Key_R)
        if key not in controls:
            return False
        if event.isAutoRepeat():
            return True
        if event.type() == QEvent.Type.KeyRelease:
            self.trex_held.discard(key)
            if key in jumps and not self.trex_held.intersection(jumps):
                self.trex.release_jump()
            if key in ducks:
                self.trex.ducking = bool(self.trex_held.intersection(ducks))
            return True
        if key in self.trex_held:
            return True
        self.trex_held.add(key)
        if key in jumps:
            if self.trex.state in ("ready", "over"):
                self.toggle_run()
            if self.trex.jump():
                self.audio.play("shot")
        elif key in ducks and self.trex.state == "running":
            self.trex.ducking = True
        elif key == Qt.Key.Key_R:
            self.restart()
        elif key == Qt.Key.Key_P:
            self.toggle_run()
        elif key == Qt.Key.Key_Escape and self.trex.state == "running":
            self.stop()
        self._draw_trex(send=self.trex.state == "running")
        return True
