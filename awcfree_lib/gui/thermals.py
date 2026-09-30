"""Live thermal workspace with asynchronous requests to the privileged service."""
from __future__ import annotations

from collections import deque
import threading
import time
import os
from pathlib import Path
import pwd
import shutil

from PyQt6.QtCore import QObject, QPointF, QProcess, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen, QRadialGradient
from PyQt6.QtWidgets import (
    QCheckBox, QGridLayout, QHBoxLayout, QLabel, QLayout, QPushButton, QScrollArea, QSlider,
    QVBoxLayout, QWidget,
)

from ..thermals import ThermalBackend, ThermalClient, ThermalError
from . import theme
from .widgets import Panel, SectionTitle

PROFILE_TEXT = {
    "cool": ("Cool", "Prioritise cooler operation"),
    "quiet": ("Quiet", "Reduce fan noise"),
    "balanced": ("Balanced", "Everyday performance"),
    "balanced-performance": ("Balanced +", "A little more performance"),
    "performance": ("Performance", "Prioritise performance"),
    "custom": ("Custom", "Adjust individual fan boost"),
    "low-power": ("Low power", "Prioritise efficiency"),
}


class ThermalMonitor(QObject):
    updated = pyqtSignal(dict)

    def __init__(self, backend=None, parent=None):
        super().__init__(parent)
        self.backend = backend or ThermalBackend()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread = None

    def start(self):
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def refresh(self):
        self._wake.set()

    def stop(self):
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def _run(self):
        while not self._stop.is_set():
            self._wake.clear()
            try:
                data = self.backend.snapshot()
                try:
                    ThermalClient().request({"action": "ping"})
                    data["service_ready"] = True
                except ThermalError as exc:
                    data["service_ready"] = False
                    data["service_error"] = str(exc)
            except Exception as exc:
                data = {"available": False, "error": str(exc), "fans": [],
                        "temperatures": [], "choices": [], "profile": None}
            if not self._stop.is_set():
                self.updated.emit(data)
            self._wake.wait(2)


class ThermalWriter(QObject):
    finished = pyqtSignal(bool, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.thread = None

    def submit(self, request):
        # Only one write can be in flight; the page disables controls until completion.
        def write():
            try:
                ThermalClient().request(request)
                self.finished.emit(True, "Applied. Refreshing the readings from your device…")
            except (ThermalError, OSError) as exc:
                self.finished.emit(False, str(exc))
        self.thread = threading.Thread(target=write, daemon=True)
        self.thread.start()


class FanRotor(QWidget):
    """Stylised RPM-driven rotor; no motion for missing or stopped sensors."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(76, 76)
        self.rpm = None
        self.angle = 0.0
        self.motion = True
        self._last = time.monotonic()
        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self._advance)

    def set_rpm(self, rpm):
        self.rpm = rpm
        self.setAccessibleName("Fan speed unavailable" if rpm is None else f"Fan: {rpm} RPM")
        self._sync()
        self.update()

    def _sync(self):
        active = self.isVisible() and self.motion and self.rpm is not None and self.rpm > 0
        if active and not self.timer.isActive():
            self._last = time.monotonic()
            self.timer.start()
        elif not active:
            self.timer.stop()

    def showEvent(self, event):
        self._sync()
        super().showEvent(event)

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)

    def _advance(self):
        now = time.monotonic()
        # Deliberately slowed for legibility; proportional, not physical rotation.
        self.angle = (self.angle + min(self.rpm or 0, 10000) * .045 * min(now-self._last, .1)) % 360
        self._last = now
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.translate(self.width()/2, self.height()/2)
        colour = QColor("#7ee2c4" if self.rpm else "#647889")
        glow = QRadialGradient(0, 0, 37)
        halo = QColor(colour); halo.setAlpha(55)
        glow.setColorAt(0, halo); glow.setColorAt(1, QColor(0, 0, 0, 0))
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(glow)
        p.drawEllipse(QPointF(0, 0), 37, 37)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor("#36545c"), 1))
        p.drawEllipse(QPointF(0, 0), 32, 32)
        p.setPen(QPen(colour, 2))
        p.drawArc(QRectF(-32, -32, 64, 64), 25*16, 75*16)
        p.rotate(self.angle)
        for _ in range(7):
            blade = QPainterPath(QPointF(5, -3))
            blade.cubicTo(12, -23, 29, -24, 26, -9)
            blade.cubicTo(23, 0, 11, 6, 5, 3)
            blade.closeSubpath()
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(colour)
            p.drawPath(blade)
            p.rotate(360/7)
        p.setBrush(QColor("#152630")); p.setPen(QPen(colour, 1.5))
        p.drawEllipse(QPointF(0, 0), 7, 7)
        p.end()


class TemperatureChart(QWidget):
    """Two minutes of real samples; gaps stay gaps when a sensor is unavailable."""
    def __init__(self):
        super().__init__()
        self.samples = deque(maxlen=120)
        self.setMinimumHeight(150)

    def append(self, cpu, gpu):
        self.samples.append((time.monotonic(), cpu, gpu))
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0, 12, -34, -20)
        values = [v for _, a, b in self.samples for v in (a, b) if v is not None]
        ceiling = max(100, int(max(values, default=0) / 25 + 1) * 25)
        p.setFont(theme.mono_font(7))
        for fraction in (0, .25, .5, .75, 1):
            y = r.bottom() - fraction * r.height()
            p.setPen(QPen(QColor("#273640"), 1))
            p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
            p.setPen(theme.INK_FAINT)
            p.drawText(QRectF(r.right()+5, y-7, 30, 15),
                       str(round(ceiling*fraction)) + "°")
        if not values:
            p.setPen(theme.INK_DIM)
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, "Waiting for temperature samples")
        now = self.samples[-1][0] if self.samples else time.monotonic()
        for channel, colour in ((1, "#7ee2c4"), (2, "#78aaff")):
            path = QPainterPath()
            connected = False
            for sample in self.samples:
                if now - sample[0] > 120:
                    continue
                value = sample[channel]
                if value is None:
                    connected = False
                    continue
                point = QPointF(r.right() - (now-sample[0])/120*r.width(),
                                r.bottom() - max(0, value)/ceiling*r.height())
                if connected:
                    path.lineTo(point)
                else:
                    path.moveTo(point)
                connected = True
            p.setPen(QPen(QColor(colour), 2))
            p.drawPath(path)
        p.end()


class ThermalsPage(QScrollArea):
    def __init__(self, parent=None, backend=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.data = {}
        self.busy = False
        self.pending_action = None
        self._setup_process = None
        self._setup_action = None
        self.profile_buttons = {}
        self.fan_controls = {}
        self.monitor = ThermalMonitor(backend, self)
        self.monitor.updated.connect(self._received)
        self.writer = ThermalWriter(self)
        self.writer.finished.connect(self._finished)
        self._build()

    def _build(self):
        content = QWidget()
        self.setWidget(content)
        root = QVBoxLayout(content)
        root.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        root.setContentsMargins(0, 0, 6, 0)
        root.setSpacing(14)
        hero = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(4)
        titles.addWidget(SectionTitle("System / Thermals"))
        title = QLabel("Cool under pressure.")
        title.setObjectName("StageTitle")
        titles.addWidget(title)
        subtitle = QLabel("A live view of your cooling. Control the balance between noise and performance.")
        subtitle.setObjectName("Hint")
        subtitle.setWordWrap(True)
        titles.addWidget(subtitle)
        hero.addLayout(titles, 1)
        self.live = QLabel("CONNECTING")
        self.live.setObjectName("ModeBadge")
        hero.addWidget(self.live, 0, Qt.AlignmentFlag.AlignVCenter)
        root.addLayout(hero)

        metrics = QHBoxLayout()
        self.metrics = {}
        self.rotors = {}
        for key, name, unit in (("cpu_temp", "CPU temperature", "°C"),
                                ("gpu_temp", "GPU temperature", "°C"),
                                ("cpu_fan", "CPU fan", "RPM"), ("gpu_fan", "GPU fan", "RPM")):
            panel = Panel()
            panel.setMinimumHeight(144)
            panel.add_title(name)
            value = QLabel("—")
            value.setObjectName("MetricValue")
            line = QHBoxLayout()
            line.addWidget(value, 1)
            if key.endswith("_fan"):
                rotor = FanRotor()
                self.rotors[key] = rotor
                line.addWidget(rotor)
            panel.box.addLayout(line)
            foot = QLabel(unit)
            foot.setObjectName("Hint")
            panel.box.addWidget(foot)
            metrics.addWidget(panel, 1)
            self.metrics[key] = value
        root.addLayout(metrics)
        from ..preferences import load_preferences
        self.reduce_motion = QCheckBox("Reduce motion")
        self.reduce_motion.setChecked(load_preferences().get("reduced_motion") is True)
        self.reduce_motion.toggled.connect(self._motion_changed)
        self._motion_changed(self.reduce_motion.isChecked())
        hero.insertWidget(1, self.reduce_motion)


        columns = QHBoxLayout()
        columns.setSpacing(20)
        left = QVBoxLayout()
        left.setSpacing(16)
        profiles = Panel()
        profiles.setMinimumHeight(174)
        profiles.add_title("Thermal profile")
        self.profile_status = QLabel("Reading firmware profiles…")
        self.profile_status.setObjectName("Hint")
        profiles.box.addWidget(self.profile_status)
        self.profile_grid = QGridLayout()
        self.profile_grid.setSpacing(10)
        profiles.box.addLayout(self.profile_grid)
        left.addWidget(profiles)
        history = Panel()
        history.add_title("Temperature history / 2 minutes")
        self.chart = TemperatureChart()
        history.box.addWidget(self.chart)
        legend = QLabel("● CPU     ● GPU     ·     Updates every 2 seconds")
        legend.setText('<span style="color:#7ee2c4">● CPU</span> &nbsp; '
                       '<span style="color:#78aaff">● GPU</span> &nbsp; · &nbsp; Updates every 2 seconds')
        legend.setObjectName("Hint")
        history.box.addWidget(legend)
        left.addWidget(history, 1)
        columns.addLayout(left, 3)

        fans = Panel()
        fans.setMinimumWidth(310)
        fans.setMaximumWidth(380)
        fans.add_title("Fan boost")
        description = QLabel("Add cooling above the firmware baseline. Boost is not fan speed: 0 does not stop the fans.")
        description.setWordWrap(True)
        description.setObjectName("Hint")
        fans.box.addWidget(description)
        self.fan_box = QVBoxLayout()
        self.fan_box.setSpacing(18)
        fans.box.addLayout(self.fan_box)
        self.fan_note = QLabel("Select Custom to enable independent fan controls.")
        self.fan_note.setWordWrap(True)
        self.fan_note.setObjectName("Hint")
        fans.box.addWidget(self.fan_note)
        self.automatic = QPushButton("Return to Balanced")
        self.automatic.clicked.connect(lambda: self._apply("profile", "balanced"))
        self.automatic.setEnabled(False)
        fans.box.addWidget(self.automatic)
        fans.box.addStretch()
        columns.addWidget(fans, 2)
        root.addLayout(columns, 1)
        self.message = QLabel("Reading sensors does not change your cooling settings.")
        self.message.setObjectName("Hint")
        self.message.setWordWrap(True)
        root.addWidget(self.message)
        self.setup = QLabel()
        self.setup.setObjectName("Hint")
        self.setup.setWordWrap(True)
        self.setup.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        root.addWidget(self.setup)
        self.setup_button = QPushButton("Enable thermal controls")
        self.setup_button.clicked.connect(lambda: self._setup_service())
        root.addWidget(self.setup_button)

    def _motion_changed(self, reduced):
        for rotor in self.rotors.values():
            rotor.motion = not reduced
            rotor._sync()

    def start(self):
        self.monitor.start()

    def stop(self):
        self.monitor.stop()
        if self._setup_process is not None:
            self._setup_process.disconnect()
            self._setup_process.kill()
            self._setup_process.deleteLater()
            self._setup_process = None

    def _received(self, data):
        self.data = data
        self.live.setText("LIVE / 2 s" if data.get("available") else "UNAVAILABLE")
        temperatures = {v["label"].upper(): v["celsius"] for v in data.get("temperatures", [])}
        fan_by_label = {v["label"].upper(): v for v in data.get("fans", [])}
        for component in ("cpu", "gpu"):
            temp = temperatures.get(component.upper())
            rpm = fan_by_label.get(component.upper() + " FAN", {}).get("rpm")
            self.metrics[component+"_temp"].setText(f"{temp:.0f}" if temp is not None else "—")
            self.rotors[component+"_fan"].set_rpm(rpm)
            self.metrics[component+"_fan"].setText(f"{rpm:,}" if rpm is not None else "—")
        self.chart.append(temperatures.get("CPU"), temperatures.get("GPU"))
        choices = data.get("choices", [])
        if list(self.profile_buttons) != choices:
            while self.profile_grid.count():
                self.profile_grid.takeAt(0).widget().deleteLater()
            self.profile_buttons = {}
            for i, name in enumerate(choices):
                title, detail = PROFILE_TEXT.get(name, (name, ""))
                button = QPushButton(title)
                button.setMinimumHeight(44)
                button.setToolTip(detail)
                button.clicked.connect(lambda _=False, n=name: self._apply("profile", n))
                self.profile_grid.addWidget(button, i//3, i%3)
                self.profile_buttons[name] = button
        profile = data.get("profile")
        pretty = PROFILE_TEXT.get(profile, (profile or "Unavailable", ""))[0]
        self.profile_status.setText("Active: " + pretty)
        for name, button in self.profile_buttons.items():
            button.setProperty("on", "true" if name == profile else "false")
            button.style().unpolish(button)
            button.style().polish(button)
        live_ids = {fan["id"] for fan in data.get("fans", [])}
        for fan_id in list(self.fan_controls):
            if fan_id not in live_ids:
                self.fan_controls.pop(fan_id)["row"].deleteLater()
        for fan in data.get("fans", []):
            fan_id = fan["id"]
            if fan_id not in self.fan_controls:
                self._add_fan(fan)
            c = self.fan_controls[fan_id]
            boost = fan.get("boost")
            c["actual"].setText(f"Current boost: {boost} / 255" if boost is not None else "Boost unavailable")
            if not c["dirty"] and boost is not None:
                c["slider"].setValue(boost)
                c["dirty"] = False
        self._enable_controls()
        if not data.get("available"):
            self.message.setText(data.get("error") or "The Alienware thermal driver is unavailable. No settings were changed.")

    def _add_fan(self, fan):
        row = QWidget()
        box = QVBoxLayout(row)
        box.setContentsMargins(0, 6, 0, 0)
        box.setSpacing(6)
        box.addWidget(SectionTitle(fan["label"]))
        actual = QLabel()
        actual.setObjectName("Hint")
        box.addWidget(actual)
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(0, 255)
        slider.setAccessibleName(fan["label"] + " boost")
        box.addWidget(slider)
        value = QLabel("0 / 255")
        value.setObjectName("Hint")
        box.addWidget(value)
        apply = QPushButton("Apply boost")
        apply.setMinimumHeight(36)
        box.addWidget(apply)
        row.setMinimumHeight(125)
        self.fan_box.addWidget(row)
        control = {"row": row, "actual": actual, "slider": slider, "value": value,
                   "apply": apply, "dirty": False}
        self.fan_controls[fan["id"]] = control
        def changed(v):
            control["dirty"] = True
            value.setText(f"{v} / 255")
        slider.valueChanged.connect(changed)
        apply.clicked.connect(lambda: self._apply("boost", str(fan["id"]), str(slider.value())))

    def _enable_controls(self):
        ready = self.data.get("service_ready", False)
        writable = self.data.get("available", False) and not self.busy
        for button in self.profile_buttons.values():
            button.setEnabled(writable)
        self.automatic.setEnabled(writable and "balanced" in self.data.get("choices", []))
        fans = {f["id"]: f for f in self.data.get("fans", [])}
        for fan_id, c in self.fan_controls.items():
            enabled = ready and writable and self.data.get("profile") == "custom" and fans.get(fan_id, {}).get("controllable", False)
            c["slider"].setEnabled(enabled)
            c["apply"].setEnabled(enabled)
        self.setup.setText("Thermal service connected · No password prompts. Settings remain active after closing."
                           if ready else self.data.get("service_error", "Thermal service unavailable") +
                           " · One-time setup: sudo sh packaging/install-thermals.sh")
        self.setup_button.setVisible(not ready)
        self.setup_button.setEnabled(writable)

    def _setup_service(self, action=None, args=()):
        if self.busy or not self.data.get("available"):
            return
        pkexec = shutil.which("pkexec")
        if not pkexec:
            self.message.setText("Install polkit (pkexec), or run: sudo sh packaging/install-thermals.sh")
            return
        self.busy = True
        self._setup_action = (action, args)
        process = QProcess(self)
        self._setup_process = process
        process.finished.connect(self._setup_finished)
        process.errorOccurred.connect(self._setup_error)
        self._enable_controls()
        self.message.setText("Waiting for administrator authentication to enable thermal controls…")
        installer = Path(__file__).resolve().parents[2] / "packaging/install_thermals.py"
        process.start(pkexec, ["/usr/bin/python3", "-I", str(installer),
                              "--user", pwd.getpwuid(os.getuid()).pw_name])

    def _setup_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self._complete_setup(False, "Could not start administrator authentication.")

    def _setup_finished(self, code, status):
        if self._setup_process is None:
            return
        message = bytes(self._setup_process.readAllStandardError()).decode(errors="replace").strip()
        self._complete_setup(code == 0 and status == QProcess.ExitStatus.NormalExit,
                             message or "Thermal setup was cancelled or failed.")

    def _complete_setup(self, ok, message):
        process, self._setup_process = self._setup_process, None
        if process is not None:
            process.deleteLater()
        action, args = self._setup_action or (None, ())
        self._setup_action = None
        self.busy = False
        if ok:
            self.data["service_ready"] = True
            self.data.pop("service_error", None)
        self.message.setText("Thermal controls enabled." if ok else message)
        self._enable_controls()
        self.monitor.refresh()
        if ok and action is not None:
            self._apply(action, *args)

    def _apply(self, action, *args):
        if self.busy:
            return
        if not self.data.get("service_ready", False):
            self._setup_service(action, args)
            return
        self.busy = True
        self._enable_controls()
        self.message.setText("Applying through the thermal service…")
        self.pending_action = (action, args)
        request = ({"action": "profile", "name": args[0]} if action == "profile" else
                   {"action": "boost", "fan": int(args[0]), "value": int(args[1])})
        self.writer.submit(request)

    def _finished(self, ok, message):
        self.busy = False
        self.message.setText(message)
        action, args = self.pending_action or (None, ())
        if action == "boost" and int(args[0]) in self.fan_controls:
            self.fan_controls[int(args[0])]["dirty"] = False
        elif action == "profile":
            for c in self.fan_controls.values():
                c["dirty"] = False
        self.pending_action = None
        self.monitor.refresh()
        self._enable_controls()
