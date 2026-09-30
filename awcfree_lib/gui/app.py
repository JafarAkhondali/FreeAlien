"""The control panel window.

USB writes take a few milliseconds and the panel fires them on every drag of the
colour picker, so all hardware work happens on a worker thread.  Requests are
coalesced rather than queued: while a write is in flight, newer requests replace
the pending one instead of piling up, which is what keeps dragging the picker
smooth instead of lagging seconds behind the cursor.
"""
from __future__ import annotations

import queue
import threading

from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QLinearGradient, QRadialGradient, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication, QColorDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QScrollArea, QSizePolicy, QSlider, QStackedWidget, QTabWidget, QVBoxLayout, QWidget,
)

from .. import layout as kb_layout
from ..devices import Chassis, Keyboard
from ..errors import AwcfreeError
from ..protocol import v4, v5
from . import theme
from .branding import app_icon
from .keyboard_view import KeyboardView
from .thermals import ThermalsPage
from .games import GamesPage
from .sounds import SoundsPage
from .model import Presets, chassis_zones
from . import parts as partdefs
from .widgets import (
    ColourSlot, HueBar, Panel, PartBar, SectionTitle, StatusChip, SVField, Swatches,
    BrandMark, ZoneCard,
)

Rgb = tuple[int, int, int]


class Hardware(QObject):
    """Owns both controllers on a worker thread."""

    ready = pyqtSignal(bool, bool, dict)
    failed = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__()
        self.keyboard: Keyboard | None = None
        self.chassis: Chassis | None = None
        self.problems: dict[str, str] = {}
        self._keyboard_per_key = False
        self._jobs: queue.Queue = queue.Queue()
        # Coalescing slots: a newer request for the same thing replaces the older.
        self._latest: dict[str, tuple] = {}
        self._latest_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        with self._latest_lock:
            self._stop.set()
            # Drain already accepted state before closing the devices.
            self._jobs.put(None)
        self._thread.join(timeout=2.0)

    # --- public API (called from the UI thread) ----------------------------
    def submit(self, slot: str, fn, *args) -> None:
        with self._latest_lock:
            if self._stop.is_set():
                return
            pending = slot in self._latest
            self._latest[slot] = (fn, args)
            if not pending:
                self._jobs.put(slot)

    # --- worker ------------------------------------------------------------
    def _open(self) -> None:
        try:
            self.keyboard = Keyboard()
            self.keyboard.open()
            self.keyboard.take_control()
            self._keyboard_per_key = True
        except AwcfreeError as exc:
            self.problems["keyboard"] = str(exc)
            if self.keyboard is not None:
                self.keyboard.close()
                self.keyboard = None
        try:
            self.chassis = Chassis()
            self.chassis.open()
        except AwcfreeError as exc:
            self.problems["chassis"] = str(exc)
            if self.chassis is not None:
                self.chassis.close()
                self.chassis = None
        self.ready.emit("keyboard" not in self.problems, "chassis" not in self.problems,
                        dict(self.problems))

    def _run(self) -> None:
        self._open()
        while True:
            slot = self._jobs.get()
            if slot is None:
                break
            with self._latest_lock:
                job = self._latest.pop(slot, None)
            if job is None:
                continue  # a newer request already ran for this slot
            fn, args = job
            try:
                fn(*args)
            except AwcfreeError as exc:
                self.failed.emit(str(exc))
            except Exception as exc:  # a bug here must not kill the worker
                self.failed.emit(f"{type(exc).__name__}: {exc}")
        for dev in (self.keyboard, self.chassis):
            if dev is not None:
                try:
                    dev.close()
                except AwcfreeError:
                    pass

    # --- operations --------------------------------------------------------
    def write_keys(self, colours: dict[int, Rgb]) -> None:
        if self.keyboard is None:
            raise AwcfreeError("Keyboard unavailable; colour was not applied")
        # Mode belongs to the worker: a newer paint can replace a queued takeover.
        if not self._keyboard_per_key:
            self.keyboard.take_control()
            self._keyboard_per_key = True
        self.keyboard.set_many(colours)
        self.keyboard.flush()

    def keys_take_control(self, colours: dict[int, Rgb]) -> None:
        if self.keyboard is None:
            raise AwcfreeError("Keyboard unavailable; colour was not applied")
        self.keyboard.take_control()
        self._keyboard_per_key = True
        self.keyboard.set_many(colours)
        self.keyboard.flush(force=True)

    def run_effect(self, name: str, primary: Rgb, secondary: Rgb, tempo: int) -> None:
        """Run a controller-side effect with the colour mode the effect actually wants.

        The mode is not a free choice: rainbow generates its own hues and ignores
        both colours, the dual wave and the mixed pulse read a pair, and everything
        else uses the primary alone. `v5.EFFECT_COLOURS` holds which is which.
        """
        if self.keyboard is None:
            raise AwcfreeError("Keyboard unavailable; effect was not applied")
        self._keyboard_per_key = False
        mode = v5.EFFECT_COLOURS.get(name, 1)
        self.keyboard.effect(name, tempo=tempo, colour_mode=mode,
                             primary=primary, secondary=secondary)

    def write_zone(self, zone: int, colour: Rgb) -> None:
        if self.chassis is None:
            raise AwcfreeError("Chassis unavailable; lighting was not applied")
        if zone == v4.ZONE_POWER:
            self.chassis.set_power_all(colour, colour)
        else:
            self.chassis.static({zone: colour})

    def zone_effect(self, zones: tuple[int, ...], kind: str, colour: Rgb,
                    secondary: Rgb = (0, 0, 0), persist: bool = False) -> None:
        """Run a chassis effect on one or more zones.

        Each zone gets its own transaction. Selecting several zones into a single
        `zone_select` would make them share one animation, and the controller then
        runs them in lockstep -- fine for a solid colour, wrong for anything with
        motion, where the point is that each surface has its own phase.
        """
        if self.chassis is None:
            raise AwcfreeError("Chassis unavailable; lighting was not applied")
        for zone in zones:
            if kind == "spectrum":
                self.chassis.spectrum(zone, persist=persist)
            elif kind == "breathe":
                self.chassis.morph(zone, [colour, (0, 0, 0)], persist=persist)
            elif kind == "morph":
                # Chassis.morph picks the right encoding for a pair; do not expand
                # it here into a longer chain, which would use the spectrum shape.
                self.chassis.morph(zone, [colour, secondary], persist=persist)
            elif kind == "pulse":
                self.chassis.pulse(zone, colour, persist=persist)
            elif kind == "static":
                self.chassis.static({zone: colour}, persist=persist)

    def set_brightness(self, level: int) -> None:
        if self.chassis is None:
            raise AwcfreeError("Chassis unavailable; brightness was not applied")
        self.chassis.brightness(level)

    def set_power_profiles(self, ac: Rgb | None, battery: Rgb | None) -> None:
        if self.chassis is None:
            raise AwcfreeError("Chassis unavailable; power profiles were not applied")
        for name in v4.POWER_PROFILES:
            colour = ac if name.startswith("ac") else battery
            if colour is not None:
                self.chassis.set_power_profile(name, [colour])


class Backdrop(QWidget):
    """The window background: two soft colour fields, drawn once per resize."""

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect()
        base = QLinearGradient(0, 0, 0, r.height())
        base.setColorAt(0.0, QColor("#111b22"))
        base.setColorAt(1.0, QColor("#090e14"))
        p.fillRect(r, base)

        for cx, cy, colour, size in (
            (0.08, 0.0, QColor(53, 140, 128), 0.7),
            (1.0, 0.8, QColor(53, 76, 130), 0.7),
        ):
            g = QRadialGradient(r.width() * cx, r.height() * cy,
                                max(r.width(), r.height()) * size)
            c = QColor(colour); c.setAlpha(24)
            g.setColorAt(0.0, c)
            g.setColorAt(1.0, QColor(colour.red(), colour.green(), colour.blue(), 0))
            p.fillRect(r, g)
        p.end()



class MainWindow(QWidget):
    """One part at a time.

    The earlier version showed the keyboard, the chassis zones and every control
    for all of them at once, and selecting a zone left the keyboard's own controls
    sitting there competing for the same colour picker.  Here a part is chosen
    first and the sidebar then offers only what that part can do -- per-key
    selection for the keyboard, chassis effects for the touchpad and lid, two
    profile colours for the power button, which has no colour of its own.
    """

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("FreeAlien")
        self.setWindowIcon(app_icon())
        self.resize(1280, 820)
        self.setMinimumSize(1160, 700)

        self.hw = Hardware()
        self.presets = Presets()
        self.colours: dict[int, Rgb] = {led: (0, 0, 0) for led in kb_layout.CELLS}
        self.zone_colours: dict[int, Rgb] = {
            p.zone: (0, 0, 0) for p in partdefs.ALL if p.zone is not None
        }
        self.colour = QColor("#5b8cff")
        self.colour_b = QColor("#ff4dcb")
        self.active_slot = "a"
        self.part_colours = {p.key: (QColor(self.colour), QColor(self.colour_b), "a")
                             for p in partdefs.ALL}
        self.power_colours: dict[str, Rgb] = {}
        self.brightness_sliders: list[QSlider] = []
        self.effect_colour_controls: dict[str, dict] = {}
        self.part = partdefs.KEYBOARD
        self.effect_choice: dict[str, str | None] = {p.key: None for p in partdefs.ALL}

        self._build()
        self._show_part(partdefs.KEYBOARD)
        self._workspace_changed("lighting")
        self.hw.ready.connect(self._on_ready)
        self.hw.failed.connect(lambda m: self._toast(m, error=True))
        self.hw.start()

    # --- construction ------------------------------------------------------
    def _build(self) -> None:
        self.backdrop = Backdrop(self)
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 22, 28, 22)
        root.setSpacing(22)
        root.addLayout(self._header())

        body = QHBoxLayout()
        body.setSpacing(22)
        stage = Panel()
        stage.setObjectName("Stage")
        stage.box.setContentsMargins(24, 22, 24, 20)
        stage.box.addLayout(self._stage())
        body.addWidget(stage, 1)
        body.addWidget(self._sidebar())
        lighting = QWidget()
        lighting.setLayout(body)
        self.workspaces = QStackedWidget()
        self.workspaces.addWidget(lighting)
        self.games = GamesPage(self.hw, lambda: self.colours, self._restore_game_colours)
        self.mines_shortcut = QShortcut(QKeySequence("Ctrl+Shift+M"), self)
        self.mines_shortcut.activated.connect(self._open_mines_from_keyboard)
        self.workspaces.addWidget(self.games)
        self.thermals = ThermalsPage()
        self.workspaces.addWidget(self.thermals)
        self.sounds = SoundsPage()
        self.workspaces.addWidget(self.sounds)
        content = QHBoxLayout()
        content.setSpacing(18)
        content.addWidget(self._navigation(), 0)
        content.addWidget(self.workspaces, 1)
        root.addLayout(content, 1)

        self.toast = QLabel("", self)
        self.toast.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.toast.setFont(theme.ui_font(9, theme.QFont.Weight.Medium))
        self.toast.hide()
        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(self.toast.hide)

    def _header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addStretch(1)
        row.addStretch(1)
        self.chip_kb = StatusChip("Keyboard")
        self.chip_elc = StatusChip("Chassis")
        row.addWidget(self.chip_kb)
        row.addWidget(self.chip_elc)
        return row

    def _navigation(self) -> QWidget:
        rail = QWidget()
        rail.setFixedWidth(178)
        box = QVBoxLayout(rail)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(7)
        brand = QWidget()
        brand_row = QHBoxLayout(brand)
        brand_row.setContentsMargins(0, 0, 0, 0)
        brand_row.setSpacing(8)
        brand_row.addWidget(BrandMark())
        brand_name = QLabel("FreeAlien")
        brand_name.setObjectName("Brand")
        brand_row.addWidget(brand_name)
        brand_row.addStretch(1)
        brand.setObjectName("Brand")
        box.addWidget(brand)
        box.addWidget(SectionTitle("WORKSPACE"))
        self.nav_buttons: dict[str, QPushButton] = {}
        for key, label in (("lighting", "◈  Lighting"), ("games", "▦  Games"),
                           ("thermals", "◉  Thermals"), ("sounds", "♫  Sounds")):
            button = QPushButton(label)
            button.setCheckable(True)
            button.setProperty("nav", "true")
            button.setFixedHeight(43)
            button.clicked.connect(lambda _=False, k=key: self._workspace_changed(k))
            box.addWidget(button)
            self.nav_buttons[key] = button
        box.addSpacing(12)
        self.part_nav_title = SectionTitle("SURFACE")
        box.addWidget(self.part_nav_title)
        self.part_nav_buttons: dict[str, QPushButton] = {}
        for part in partdefs.ALL:
            button = QPushButton(part.name)
            button.setCheckable(True)
            button.setProperty("nav", "sub")
            button.setFixedHeight(36)
            button.clicked.connect(lambda _=False, k=part.key: self._show_part(partdefs.BY_KEY[k]))
            box.addWidget(button)
            self.part_nav_buttons[part.key] = button
        box.addStretch(1)
        foot = QLabel("M16 R2  ·  LINUX")
        foot.setObjectName("Hint")
        box.addWidget(foot)
        return rail

    def _workspace_changed(self, key: str) -> None:
        index = {"lighting": 0, "games": 1, "thermals": 2, "sounds": 3}[key]
        if self.workspaces.currentIndex() == 1 and index != 1:
            self.games.stop(restore=True)
        self.workspaces.setCurrentIndex(index)
        for name, button in self.nav_buttons.items():
            self._restyle(button, name == key)
            button.setChecked(name == key)
        self.part_nav_title.setVisible(key == "lighting")
        for button in self.part_nav_buttons.values():
            button.setVisible(key == "lighting")
        if key == "thermals":
            self.thermals.start()
        elif key == "games":
            self.games.enter()

    def _open_mines_from_keyboard(self) -> None:
        if self.workspaces.currentWidget() is self.games and self.games.mode == "mines":
            self.games.board.setFocus()
            return
        self._workspace_changed("games")
        self.games.set_mode("mines")
        self.games.board.setFocus()

    def _stage(self) -> QVBoxLayout:
        col = QVBoxLayout()
        col.setSpacing(16)
        heading = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(6)
        titles.addWidget(SectionTitle("Your device / AlienFX"))
        self.stage_title = QLabel("Keyboard")
        self.stage_title.setObjectName("StageTitle")
        titles.addWidget(self.stage_title)
        heading.addLayout(titles)
        heading.addStretch()
        self.mode_label = QLabel("PER-KEY COLOUR")
        self.mode_label.setObjectName("ModeBadge")
        heading.addWidget(self.mode_label, 0, Qt.AlignmentFlag.AlignVCenter)
        col.addLayout(heading)

        self.tools = QHBoxLayout()
        self.tools.setSpacing(8)
        self.btn_all = QPushButton("Select all")
        self.btn_none = QPushButton("Clear")
        for b, slot in ((self.btn_all, self._select_all), (self.btn_none, self._clear_sel)):
            b.setFont(theme.ui_font(9, theme.QFont.Weight.DemiBold))
            b.setFixedWidth(100)
            b.clicked.connect(slot)
            self.tools.addWidget(b)
        self.tools.addStretch(1)
        self.sel_label = QLabel("whole keyboard")
        self.sel_label.setFont(theme.mono_font(8))
        self.sel_label.setStyleSheet(f"color: {theme.INK_FAINT.name()};")
        self.tools.addWidget(self.sel_label)
        col.addLayout(self.tools)

        self.kbview = KeyboardView()
        self.kbview.selectionChanged.connect(self._on_selection)
        self.kbview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        col.addWidget(self.kbview, 1)

        zrow = QHBoxLayout()
        zrow.setSpacing(10)
        self.zone_cards: dict[int, ZoneCard] = {}
        shapes = {partdefs.TOUCHPAD.key: "pad", partdefs.LOGO.key: "head",
                  partdefs.POWER.key: "power"}
        for part in partdefs.ALL:
            if part.zone is None:
                continue
            card = ZoneCard(part.zone, part.name, part.caption, shapes[part.key])
            card.clicked.connect(
                lambda _zid, k=part.key: self._show_part(partdefs.BY_KEY[k]))
            self.zone_cards[part.zone] = card
            zrow.addWidget(card)
        col.addWidget(SectionTitle("Chassis lighting"))
        col.addLayout(zrow)

        self.hint = QLabel("")
        self.hint.setObjectName("Hint")
        self.hint.setWordWrap(True)
        self.hint.setFont(theme.ui_font(8))
        col.addWidget(self.hint)
        return col

    def _sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setFixedWidth(332)
        box = QVBoxLayout(sidebar)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(14)
        title = QLabel("Make it yours.")
        title.setObjectName("InspectorTitle")
        box.addWidget(title)
        subtitle = QLabel("Colour, motion, and a little personality.")
        subtitle.setObjectName("Hint")
        box.addWidget(subtitle)
        self.inspector = QTabWidget()
        box.addWidget(self.inspector, 1)

        def tab(label):
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            page = QWidget()
            layout = QVBoxLayout(page)
            layout.setContentsMargins(0, 16, 4, 0)
            layout.setSpacing(14)
            scroll.setWidget(page)
            self.inspector.addTab(scroll, label)
            return layout

        colour_box = tab("Colour")
        colour_box.addWidget(self._panel_colour())
        self.stack = QStackedWidget()
        self.pages: dict[str, int] = {}
        self.effects_stack = QStackedWidget()
        for part in partdefs.ALL:
            self.pages[part.key] = self.stack.addWidget(self._page_for(part))
            page = QWidget()
            effects = QVBoxLayout(page)
            effects.setContentsMargins(0, 0, 0, 0)
            effects.setSpacing(14)
            if part.effects:
                effects.addWidget(self._build_effects(part))
            else:
                note = QLabel("Power follows your machine.\nSet AC and battery colours in the Colour tab.")
                note.setWordWrap(True)
                note.setObjectName("Hint")
                effects.addWidget(note)
            if part.brightness:
                effects.addWidget(self._build_brightness(part))
            effects.addStretch()
            self.effects_stack.addWidget(page)
        colour_box.addWidget(self.stack)
        colour_box.addStretch()
        tab("Effects").addWidget(self.effects_stack)
        saved = tab("Saved")
        saved.addWidget(self._panel_presets())
        saved.addStretch()
        return sidebar

    # --- colour panel ------------------------------------------------------
    def _panel_colour(self) -> Panel:
        p = Panel()
        p.add_title("Colour")
        self.sv = SVField()
        self.hue = HueBar()
        p.box.addWidget(self.sv)
        p.box.addWidget(self.hue)

        row = QHBoxLayout()
        row.setSpacing(9)
        self.slot_a = ColourSlot("A")
        self.slot_b = ColourSlot("B")
        self.slot_a.clicked.connect(lambda: self._use_slot("a"))
        self.slot_b.clicked.connect(lambda: self._use_slot("b"))
        self.hex = QLineEdit(self.colour.name())
        self.hex.setFont(theme.mono_font(9))
        row.addWidget(self.slot_a)
        row.addWidget(self.slot_b)
        row.addWidget(self.hex, 1)
        p.box.addLayout(row)

        self.pair_note = QLabel("")
        self.pair_note.setObjectName("Hint")
        self.pair_note.setWordWrap(True)
        self.pair_note.setFont(theme.ui_font(8))
        p.box.addWidget(self.pair_note)

        self.swatches = Swatches()
        p.box.addWidget(self.swatches)

        self.sv.changed.connect(self._sv_changed)
        self.hue.changed.connect(self._hue_changed)
        self.swatches.picked.connect(self._set_colour)
        self.hex.editingFinished.connect(self._hex_entered)
        self.slot_a.set_colour(self.colour)
        self.slot_b.set_colour(self.colour_b)
        self._use_slot("a")
        return p

    # --- per-part pages ----------------------------------------------------
    def _page_for(self, part: partdefs.Part) -> QWidget:
        page = QWidget()
        box = QVBoxLayout(page)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(12)

        apply_panel = Panel()
        apply_panel.add_title(part.name)
        blurb = QLabel(part.blurb)
        blurb.setObjectName("Hint")
        blurb.setWordWrap(True)
        blurb.setFont(theme.ui_font(8))
        apply_panel.box.addWidget(blurb)

        if part.power_profiles:
            self._build_power(apply_panel, part)
        else:
            self._build_apply(apply_panel, part)
        box.addWidget(apply_panel)

        box.addStretch(1)
        return page

    def _build_apply(self, panel: Panel, part: partdefs.Part) -> None:
        row = QHBoxLayout()
        row.setSpacing(8)
        if part.per_key:
            paint = QPushButton("Paint selection")
            paint.setProperty("accent", "true")
            paint.clicked.connect(self._paint)
            every = QPushButton("Every key")
            every.clicked.connect(self._paint_all)
            row.addWidget(paint)
            row.addWidget(every)
        else:
            paint = QPushButton(f"Set {part.name.lower()}")
            paint.setProperty("accent", "true")
            paint.clicked.connect(self._paint)
            off = QPushButton("Off")
            off.setProperty("danger", "true")
            off.clicked.connect(lambda: self._zone_static((0, 0, 0)))
            row.addWidget(paint)
            row.addWidget(off)
        for i in range(row.count()):
            w = row.itemAt(i).widget()
            if w:
                w.setFont(theme.ui_font(9, theme.QFont.Weight.DemiBold))
        panel.box.addLayout(row)

        if part.per_key:
            off = QPushButton("All keys off")
            off.setProperty("danger", "true")
            off.setFont(theme.ui_font(9, theme.QFont.Weight.DemiBold))
            off.clicked.connect(self._all_keys_off)
            panel.box.addWidget(off)

    def _build_power(self, panel: Panel, part: partdefs.Part) -> None:
        grid = QGridLayout()
        grid.setSpacing(8)
        ac = QPushButton("Set AC colour (A)")
        ac.setProperty("accent", "true")
        ac.clicked.connect(lambda: self._set_power(use_b=False))
        bat = QPushButton("Set battery colour (B)")
        bat.clicked.connect(lambda: self._set_power(use_b=True))
        both = QPushButton("Apply both")
        both.clicked.connect(lambda: self._set_power(both=True))
        off = QPushButton("Off")
        off.setProperty("danger", "true")
        off.clicked.connect(lambda: self._set_power(black=True))
        for i, b in enumerate((ac, bat, both, off)):
            b.setFont(theme.ui_font(9, theme.QFont.Weight.DemiBold))
            grid.addWidget(b, i // 2, i % 2)
        panel.box.addLayout(grid)

    def _build_effects(self, part: partdefs.Part) -> Panel:
        panel = Panel()
        panel.add_title("Effects")
        grid = QGridLayout()
        grid.setSpacing(7)
        buttons: dict[str, QPushButton] = {}
        cols = 2
        for i, name in enumerate(part.effects):
            label = name.replace("_", " ").title()
            if name in part.pair_effects:
                label += " · A+B"
            b = QPushButton(label)
            b.setFont(theme.ui_font(8, theme.QFont.Weight.DemiBold))
            if name == "off":
                b.setProperty("danger", "true")
            if name in part.pair_effects:
                b.setToolTip("Uses both colours, A and B")
            b.clicked.connect(lambda _=False, n=name, k=part.key: self._run_effect(k, n))
            buttons[name] = b
            grid.addWidget(b, i // cols, i % cols)
        panel.box.addLayout(grid)
        setattr(self, f"_fx_{part.key}", buttons)

        colours = QWidget()
        colours_box = QVBoxLayout(colours)
        colours_box.setContentsMargins(0, 6, 0, 0)
        colours_box.setSpacing(8)
        note = QLabel("Choose an effect to edit its colours.")
        note.setObjectName("Hint")
        note.setWordWrap(True)
        colours_box.addWidget(note)
        controls = {"note": note}
        for slot in ("a", "b"):
            row = QWidget()
            row_box = QHBoxLayout(row)
            row_box.setContentsMargins(0, 0, 0, 0)
            label = QLabel(f"Colour {slot.upper()}")
            swatch = QPushButton()
            swatch.setFixedSize(32, 32)
            swatch.setAccessibleName(f"Choose colour {slot.upper()}")
            swatch.setToolTip(f"Choose effect colour {slot.upper()}")
            swatch.clicked.connect(lambda _=False, s=slot: self._pick_effect_colour(s))
            edit = QLineEdit()
            edit.setFont(theme.mono_font(9))
            edit.setAccessibleName(f"Effect colour {slot.upper()} hex")
            edit.editingFinished.connect(lambda s=slot, e=edit: self._edit_effect_colour(s, e))
            row_box.addWidget(label)
            row_box.addWidget(swatch)
            row_box.addWidget(edit, 1)
            colours_box.addWidget(row)
            controls[slot] = (row, swatch, edit)
        self.effect_colour_controls[part.key] = controls
        panel.box.addWidget(colours)

        if part.tempo:
            row = QHBoxLayout()
            lab = QLabel("Tempo")
            lab.setObjectName("Hint")
            lab.setFont(theme.ui_font(8))
            self.tempo = QSlider(Qt.Orientation.Horizontal)
            self.tempo.setRange(1, 255)
            self.tempo.setValue(0x64)
            # Changing tempo with an effect running should take effect immediately
            # rather than waiting for the effect to be re-picked.
            self.tempo.valueChanged.connect(self._retime)
            row.addWidget(lab)
            row.addWidget(self.tempo, 1)
            panel.box.addLayout(row)
            back = QPushButton("Back to per-key")
            back.setFont(theme.ui_font(9, theme.QFont.Weight.DemiBold))
            back.clicked.connect(self._effect_off)
            panel.box.addWidget(back)

        if part.persist:
            keep = QPushButton("Keep after reboot")
            keep.setCheckable(True)
            keep.setFont(theme.ui_font(8, theme.QFont.Weight.DemiBold))
            keep.setToolTip("Write the effect into the controller so it survives a "
                            "power cycle.")
            keep.toggled.connect(lambda on, k=part.key: self._persist_changed(k, on))
            self._restyle(keep, False)
            panel.box.addWidget(keep)
            setattr(self, f"_persist_{part.key}", keep)
        return panel

    def _sync_effect_colours(self) -> None:
        controls = self.effect_colour_controls.get(self.part.key)
        if controls is None:
            return
        effect = self.effect_choice.get(self.part.key)
        automatic = effect in ("rainbow", "spectrum")
        pair = partdefs.uses_pair(self.part, effect)
        controls["note"].setText(
            "This effect generates its own colours." if automatic else
            "Two colours · click either swatch or enter a hex value." if pair else
            "Choose an effect to edit its colours." if effect is None else
            "Click the swatch or enter a hex value.")
        for slot, colour in (("a", self.colour), ("b", self.colour_b)):
            row, swatch, edit = controls[slot]
            row.setVisible(effect is not None and not automatic and (slot == "a" or pair))
            swatch.setStyleSheet(f"background: {colour.name()}; border: 1px solid #83949f; "
                                "border-radius: 8px; padding: 0;")
            if not edit.isModified():
                edit.setText(colour.name())

    def _pick_effect_colour(self, slot: str) -> None:
        current = self.colour if slot == "a" else self.colour_b
        colour = QColorDialog.getColor(current, self, f"Effect colour {slot.upper()}",
                                       QColorDialog.ColorDialogOption.DontUseNativeDialog)
        if colour.isValid():
            self._use_slot(slot)
            self._set_colour(colour)

    def _edit_effect_colour(self, slot: str, edit: QLineEdit) -> None:
        if not edit.isModified():
            return
        colour = QColor(edit.text().strip())
        edit.setModified(False)
        if colour.isValid():
            self._use_slot(slot)
            self._set_colour(colour)
        else:
            self._sync_effect_colours()

    def _persist_changed(self, part_key: str, on: bool) -> None:
        keep = getattr(self, f"_persist_{part_key}")
        self._restyle(keep, on)
        effect = self.effect_choice.get(part_key)
        if effect:
            self._run_effect(part_key, effect, announce=False)
        else:
            part = partdefs.BY_KEY[part_key]
            colour = self.zone_colours[part.zone]
            self.hw.submit(f"zone{part.zone}", self.hw.zone_effect,
                           (part.zone,), "static", colour, colour, on)

    def _build_brightness(self, part: partdefs.Part) -> Panel:
        panel = Panel()
        panel.add_title("Brightness")
        note = QLabel("Shared by the touchpad and the lid emblem — the controller has "
                      "one brightness for both.")
        note.setObjectName("Hint")
        note.setWordWrap(True)
        note.setFont(theme.ui_font(8))
        panel.box.addWidget(note)
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(0, 255)
        slider.setValue(255)
        self.brightness_sliders.append(slider)
        slider.valueChanged.connect(self._brightness_changed)
        panel.box.addWidget(slider)
        return panel

    def _brightness_changed(self, value: int) -> None:
        for slider in self.brightness_sliders:
            slider.blockSignals(True)
            slider.setValue(value)
            slider.blockSignals(False)
        self.hw.submit("bright", self.hw.set_brightness, value)

    def _panel_presets(self) -> Panel:
        p = Panel()
        p.add_title("Presets")
        row = QHBoxLayout()
        row.setSpacing(7)
        self.preset_name = QLineEdit()
        self.preset_name.setPlaceholderText("Name your lighting setup")
        self.preset_name.setFont(theme.ui_font(9))
        save = QPushButton("Save")
        save.setFont(theme.ui_font(9, theme.QFont.Weight.DemiBold))
        save.setFixedWidth(64)
        save.clicked.connect(self._save_preset)
        row.addWidget(self.preset_name, 1)
        row.addWidget(save)
        p.box.addLayout(row)
        self.preset_box = QVBoxLayout()
        self.preset_box.setSpacing(6)
        p.box.addLayout(self.preset_box)
        self._refresh_presets()
        return p

    # --- switching parts ---------------------------------------------------
    def _show_part(self, part: partdefs.Part) -> None:
        # Commit actual pending edits to the old surface before changing target.
        controls = self.effect_colour_controls.get(self.part.key)
        if controls:
            for slot in ("a", "b"):
                self._edit_effect_colour(slot, controls[slot][2])
        if self.hex.isModified():
            self._hex_entered()
        self.part_colours[self.part.key] = (QColor(self.colour), QColor(self.colour_b),
                                             self.active_slot)
        self.part = part
        a, b, slot = self.part_colours[part.key]
        self.colour, self.colour_b = QColor(a), QColor(b)
        self.slot_a.set_colour(self.colour)
        self.slot_b.set_colour(self.colour_b)
        self._use_slot(slot)
        self.stack.setCurrentIndex(self.pages[part.key])
        self.effects_stack.setCurrentIndex(self.pages[part.key])
        self.stage_title.setText(part.name)
        self._refresh_mode()
        for name, button in self.part_nav_buttons.items():
            button.setChecked(name == part.key)

        # The keyboard picture stays on screen because it is what the machine looks
        # like, but it stops taking clicks when another part has focus -- that
        # competition is what made selecting the logo feel broken.
        self.kbview.setEnabled(part.per_key)
        self.kbview.setDim(not part.per_key)
        for widget in (self.btn_all, self.btn_none):
            widget.setVisible(part.per_key)

        for zone, card in self.zone_cards.items():
            card.set_selected(zone == part.zone)

        if part.per_key:
            self._on_selection(self.kbview.selection)
            self.hint.setText("Click a key to select · drag to sweep · Shift adds · "
                              "Ctrl removes · nothing selected means every key")
        else:
            self.sel_label.setText(part.name)
            self.hint.setText(part.blurb)
        self._refresh_pair()

    def _refresh_pair(self) -> None:
        """Show slot B only when the current part and effect actually read it."""
        effect = self.effect_choice.get(self.part.key)
        shows = partdefs.uses_pair(self.part, effect)
        self.slot_b.setVisible(shows)
        if self.part.power_profiles:
            self.pair_note.setText("A is the AC colour, B the battery colour.")
        elif shows:
            self.pair_note.setText(
                f"{effect.replace('_', ' ').title()} blends A and B.")
        else:
            self.pair_note.setText("")
        self.pair_note.setVisible(bool(self.pair_note.text()))
        if not shows and self.active_slot == "b":
            self._use_slot("a")
        self._sync_effect_colours()

    # --- colour ------------------------------------------------------------
    def _use_slot(self, which: str) -> None:
        self.active_slot = which
        self.slot_a.set_active(which == "a")
        self.slot_b.set_active(which == "b")
        current = self.colour if which == "a" else self.colour_b
        h, s, v, _ = current.getHsvF()
        self.sv.set_hsv(max(h, 0.0), s, v)
        self.hue.hue = max(h, 0.0)
        self.hue.update()
        self.hex.setText(current.name())

    def _store(self, colour: QColor) -> None:
        if self.active_slot == "a":
            self.colour = QColor(colour)
            self.slot_a.set_colour(self.colour)
        else:
            self.colour_b = QColor(colour)
            self.slot_b.set_colour(self.colour_b)
        self.hex.setText(colour.name())
        self._sync_effect_colours()

    def _set_colour(self, colour: QColor) -> None:
        c = QColor(colour)
        h, s, v, _ = c.getHsvF()
        self.sv.set_hsv(max(h, 0.0), s, v)
        self.hue.hue = max(h, 0.0)
        self.hue.update()
        self._store(c)
        self._live()

    def _sv_changed(self, s: float, v: float) -> None:
        self._store(QColor.fromHsvF(self.hue.hue, s, v))
        self._live()

    def _hue_changed(self, h: float) -> None:
        self.sv.set_hsv(h, self.sv.sat, self.sv.val)
        self._store(QColor.fromHsvF(h, self.sv.sat, self.sv.val))
        self._live()

    def _hex_entered(self) -> None:
        if not self.hex.isModified():
            return
        self.hex.setModified(False)
        c = QColor(self.hex.text().strip())
        if c.isValid():
            self._set_colour(c)
        else:
            self.hex.setText((self.colour if self.active_slot == "a"
                              else self.colour_b).name())

    def _rgb(self) -> Rgb:
        return (self.colour.red(), self.colour.green(), self.colour.blue())

    def _rgb_b(self) -> Rgb:
        return (self.colour_b.red(), self.colour_b.green(), self.colour_b.blue())

    def _live(self) -> None:
        """React to the picker moving, in whatever way the current state calls for.

        Three cases, and conflating them was the bug: with an effect running, a new
        colour should re-run *that effect* in the new colour, not silently replace
        it with a flat one; with no effect, slot A paints and slot B does nothing,
        because B is a parameter rather than a colour the surface is wearing; and
        the power button never applies on drag at all, since its two colours go to
        different stored profiles and only its buttons know which.
        """
        if self.part.power_profiles:
            return
        effect = self.effect_choice.get(self.part.key)
        if effect:
            self._run_effect(self.part.key, effect, announce=False)
            return
        if self.active_slot != "a":
            return
        self._paint()

    # --- applying ----------------------------------------------------------
    def _paint(self) -> None:
        if self.part.per_key:
            rgb = self._rgb()
            for led in self.kbview.targets():
                self.colours[led] = rgb
            self.kbview.set_colours(self.colours)
            if self.effect_choice.get(self.part.key):
                # a controller-side effect owns the LEDs; per-key colour is
                # accepted but invisible until we take them back
                self.hw.submit("keyboard", self.hw.keys_take_control, dict(self.colours))
                self._mark_effect(self.part.key, None)
            else:
                self.hw.submit("keyboard", self.hw.write_keys, dict(self.colours))
        elif self.part.zone is not None:
            self._zone_static(self._rgb())

    def _paint_all(self) -> None:
        self.kbview.clear_selection()
        self._paint()

    def _all_keys_off(self) -> None:
        for led in self.colours:
            self.colours[led] = (0, 0, 0)
        self.kbview.set_colours(self.colours)
        self.hw.submit("keyboard", self.hw.keys_take_control, dict(self.colours))
        self._mark_effect(partdefs.KEYBOARD.key, None)

    def _zone_static(self, rgb: Rgb) -> None:
        zone = self.part.zone
        if zone is None:
            return
        self.zone_colours[zone] = rgb
        self.zone_cards[zone].set_colour(rgb)
        keep = getattr(self, f"_persist_{self.part.key}", None)
        self.hw.submit(f"zone{zone}", self.hw.zone_effect, (zone,), "static",
                       rgb, rgb, bool(keep and keep.isChecked()))
        self._mark_effect(self.part.key, None)

    def _set_power(self, use_b: bool = False, both: bool = False,
                   black: bool = False) -> None:
        ac = bat = None
        if black:
            ac = bat = (0, 0, 0)
        elif both:
            ac, bat = self._rgb(), self._rgb_b()
        elif use_b:
            bat = self._rgb_b()
        else:
            ac = self._rgb()
        self._queue_power(ac, bat)
        what = "AC and battery" if both else ("battery" if use_b else "AC")
        self._toast("power button off requested" if black else f"power button: {what} requested")

    def _queue_power(self, ac: Rgb | None, battery: Rgb | None) -> None:
        # AC and battery are independent state: neither may replace the other.
        for group, colour in (("ac", ac), ("battery", battery)):
            if colour is None:
                continue
            self.power_colours[group] = colour
            self.hw.submit(f"power:{group}", self.hw.set_power_profiles,
                           colour if group == "ac" else None,
                           colour if group == "battery" else None)
        colour = ac if ac is not None else battery
        if colour is not None:
            zone = partdefs.POWER.zone
            self.zone_colours[zone] = colour
            self.zone_cards[zone].set_colour(colour)

    # --- effects -----------------------------------------------------------
    def _run_effect(self, part_key: str, name: str, announce: bool = True) -> None:
        """Start an effect, or restart the running one with new colours.

        `announce` is off when the picker is driving this, so dragging a colour
        does not fire a toast on every step.
        """
        part = partdefs.BY_KEY[part_key]
        if part.per_key:
            self.hw.submit("keyboard", self.hw.run_effect, name, self._rgb(),
                           self._rgb_b(), self.tempo.value())
            uses = v5.EFFECT_COLOURS.get(name, 1)
            detail = {1: "colour A", 2: "colours A and B", 3: "its own hues"}[uses]
            self._mark_effect(part_key, name)
            if announce:
                self._toast(f"{name.replace('_', ' ')} · {detail}")
            return

        zone = part.zone
        keep = getattr(self, f"_persist_{part_key}", None)
        persist = bool(keep and keep.isChecked())
        colour = (0, 0, 0) if name == "off" else self._rgb()
        kind = "static" if name == "off" else name
        self.hw.submit(f"zone{zone}", self.hw.zone_effect, (zone,), kind,
                       colour, self._rgb_b(), persist)
        self.zone_colours[zone] = colour
        self.zone_cards[zone].set_colour(colour)
        self._mark_effect(part_key, None if name in ("off", "static") else name)
        if announce:
            tail = " · kept after reboot" if persist and name != "off" else ""
            self._toast(f"{part.name.lower()}: {name}{tail}")

    def _retime(self, _value: int) -> None:
        running = self.effect_choice.get(partdefs.KEYBOARD.key)
        if running:
            self._run_effect(partdefs.KEYBOARD.key, running, announce=False)

    def _effect_off(self) -> None:
        self.hw.submit("keyboard", self.hw.keys_take_control, dict(self.colours))
        self._mark_effect(partdefs.KEYBOARD.key, None)

    def _restore_game_colours(self) -> None:
        self.hw.submit("keyboard", self.hw.keys_take_control, dict(self.colours))
        self.kbview.set_colours(self.colours)

    def _mark_effect(self, part_key: str, name: str | None) -> None:
        self.effect_choice[part_key] = name
        buttons = getattr(self, f"_fx_{part_key}", {})
        for key, button in buttons.items():
            self._restyle(button, key == name)
        if part_key == self.part.key:
            self._refresh_pair()
            self._refresh_mode()

    def _refresh_mode(self) -> None:
        effect = self.effect_choice.get(self.part.key)
        label = (effect.replace("_", " ") if effect else
                 "power profiles" if self.part.power_profiles else
                 "per-key colour" if self.part.per_key else "static colour")
        self.mode_label.setText(label.upper())

    @staticmethod
    def _restyle(button: QPushButton, on: bool) -> None:
        button.setProperty("on", "true" if on else "false")
        button.style().unpolish(button)
        button.style().polish(button)

    # --- selection ---------------------------------------------------------
    def _on_selection(self, leds: set) -> None:
        if not self.part.per_key:
            return
        if leds:
            self.sel_label.setText(f"{len(leds)} key{'s' if len(leds) != 1 else ''}")
        else:
            self.sel_label.setText("whole keyboard")

    def _select_all(self) -> None:
        self.kbview.select_all()

    def _clear_sel(self) -> None:
        self.kbview.clear_selection()

    # --- presets -----------------------------------------------------------
    def _save_preset(self) -> None:
        name = self.preset_name.text().strip()
        if not name:
            self._toast("give the preset a name first", error=True)
            return
        self.presets.put(name, {
            "keys": {f"0x{k:02x}": list(v) for k, v in self.colours.items()},
            "zones": {str(k): list(v) for k, v in self.zone_colours.items()
                      if k != partdefs.POWER.zone},
            "power": {k: list(v) for k, v in self.power_colours.items()},
        })
        self.preset_name.clear()
        self._refresh_presets()
        self._toast(f"saved “{name}”")

    def _load_preset(self, name: str) -> None:
        data = self.presets.data.get(name)
        if not data:
            return
        for k, v in (data.get("keys") or {}).items():
            led = int(k, 16)
            if led in self.colours:
                self.colours[led] = tuple(v)
        self.kbview.set_colours(self.colours)
        self.hw.submit("keyboard", self.hw.keys_take_control, dict(self.colours))
        for k, v in (data.get("zones") or {}).items():
            zone = int(k)
            self.zone_colours[zone] = tuple(v)
            if zone in self.zone_cards:
                self.zone_cards[zone].set_colour(tuple(v))
            if zone == partdefs.POWER.zone:
                # Older presets stored only one colour for this surface.
                self._queue_power(tuple(v), tuple(v))
            else:
                self.hw.submit(f"zone{zone}", self.hw.zone_effect, (zone,), "static",
                               tuple(v), tuple(v), False)
        power = data.get("power") or {}
        self._queue_power(tuple(power["ac"]) if "ac" in power else None,
                          tuple(power["battery"]) if "battery" in power else None)
        for part in partdefs.ALL:
            self._mark_effect(part.key, None)
        self._toast(f"loaded “{name}”")

    def _refresh_presets(self) -> None:
        while self.preset_box.count():
            item = self.preset_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                while item.layout().count():
                    sub = item.layout().takeAt(0)
                    if sub.widget():
                        sub.widget().deleteLater()
        names = self.presets.names()
        if not names:
            empty = QLabel("Your favourite setups, one click away.\nPaint your device, then save it here.")
            empty.setObjectName("Hint")
            empty.setFont(theme.ui_font(8))
            self.preset_box.addWidget(empty)
            return
        for name in names:
            row = QHBoxLayout()
            row.setSpacing(6)
            load = QPushButton(name)
            load.setFont(theme.ui_font(9))
            load.clicked.connect(lambda _=False, n=name: self._load_preset(n))
            drop = QPushButton("×")
            drop.setFixedWidth(32)
            drop.setProperty("danger", "true")
            drop.clicked.connect(lambda _=False, n=name: self._delete_preset(n))
            row.addWidget(load, 1)
            row.addWidget(drop)
            self.preset_box.addLayout(row)

    def _delete_preset(self, name: str) -> None:
        self.presets.drop(name)
        self._refresh_presets()

    # --- chrome ------------------------------------------------------------
    def _on_ready(self, kb: bool, elc: bool, problems: dict) -> None:
        self.chip_kb.set_ok(kb)
        self.chip_elc.set_ok(elc)
        for key, chip in (("keyboard", self.chip_kb), ("chassis", self.chip_elc)):
            if key in problems:
                chip.setToolTip(problems[key])
        if problems:
            self._toast(next(iter(problems.values())), error=True, msec=7000)

    def _toast(self, text: str, error: bool = False, msec: int = 3000) -> None:
        self.toast.setText(text)
        colour = theme.DANGER.name() if error else theme.INK.name()
        border = theme.DANGER.name() if error else "rgba(255,255,255,0.14)"
        self.toast.setStyleSheet(
            f"background: rgba(14,16,24,0.97); color: {colour};"
            f"border: 1px solid {border}; border-radius: 16px; padding: 9px 18px;")
        self.toast.adjustSize()
        self.toast.move((self.width() - self.toast.width()) // 2,
                        self.height() - self.toast.height() - 24)
        self.toast.show()
        self.toast.raise_()
        self._toast_timer.start(msec)

    def resizeEvent(self, event) -> None:
        self.backdrop.setGeometry(self.rect())
        self.backdrop.lower()
        super().resizeEvent(event)

    def closeEvent(self, event) -> None:
        if self.thermals.busy:
            self._toast("Wait for the thermal service request to finish before closing.")
            event.ignore()
            return
        self.thermals.stop()
        self.games.stop(restore=True)
        self.sounds.close()
        self.hw.stop()
        super().closeEvent(event)


def run(argv: list[str] | None = None) -> int:
    app = QApplication(argv or [])
    app.setApplicationName("FreeAlien")
    app.setDesktopFileName("freealien")
    app.setWindowIcon(app_icon())
    app.setApplicationDisplayName("FreeAlien")
    app.setStyleSheet(theme.STYLESHEET)
    app.setFont(theme.ui_font(9))
    window = MainWindow()
    window.show()
    return app.exec()
