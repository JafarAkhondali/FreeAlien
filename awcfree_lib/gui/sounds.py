"""Keyboard sound workspace, independent of lighting and game state."""
from __future__ import annotations

from pathlib import Path
import shutil

from PyQt6.QtCore import QEvent, QProcess, Qt, pyqtSignal
from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox, QGridLayout,
    QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout, QWidget)

from .. import layout
from ..sounds.input import GlobalKeyboard, keyboard_devices
from ..sounds.playback import SoundEngine
from ..sounds.packs import PACKS, VariantPicker, key_role
from .widgets import Panel, SectionTitle

QT_NAMES = {
    Qt.Key.Key_Return: "ENTER", Qt.Key.Key_Enter: "KPENTER", Qt.Key.Key_Space: "SPACE",
    Qt.Key.Key_Backspace: "BACKSPACE", Qt.Key.Key_Delete: "DELETE", Qt.Key.Key_Tab: "TAB",
    Qt.Key.Key_Backtab: "TAB", Qt.Key.Key_CapsLock: "CAPSLOCK", Qt.Key.Key_Shift: "SHIFT",
    Qt.Key.Key_Control: "CTRL", Qt.Key.Key_Alt: "ALT", Qt.Key.Key_AltGr: "RALT",
    Qt.Key.Key_Meta: "META", Qt.Key.Key_Escape: "ESC", Qt.Key.Key_Left: "LEFT",
    Qt.Key.Key_Right: "RIGHT", Qt.Key.Key_Up: "UP", Qt.Key.Key_Down: "DOWN",
}


def qt_key_name(key):
    if key in QT_NAMES: return QT_NAMES[key]
    if Qt.Key.Key_F1 <= key <= Qt.Key.Key_F35:
        return f"F{key - Qt.Key.Key_F1 + 1}"
    if 32 <= key < 127: return chr(key).upper()
    return f"KEY_{key}"


class TypingPad(QLabel):
    def __init__(self):
        super().__init__("Click here and type to audition your pack")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumHeight(120)
        self.setObjectName("StageTitle")

    def mousePressEvent(self, event):
        self.setFocus()

    def keyPressEvent(self, event):
        event.accept()


class SoundsPage(QWidget):
    audioFailed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pack = "gaming"
        self.enabled = False
        self._app_held = set()
        self._setup_process = None
        self.picker = VariantPicker()
        self.engine = SoundEngine(failed=self.audioFailed.emit)
        self.listener = GlobalKeyboard(self)
        self.listener.pressed.connect(self._global_press)
        self.listener.failed.connect(self._fail)
        self.listener.changed.connect(self._capture_changed)
        self.audioFailed.connect(self._fail)
        app = QApplication.instance()
        if app is not None: app.installEventFilter(self)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(16)
        root.addWidget(SectionTitle("KEYBOARD SOUNDS"))
        title = QLabel("Give your keys a voice")
        title.setObjectName("StageTitle")
        root.addWidget(title)
        hint = QLabel("Choose a pack. Type to try it.")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        root.addWidget(hint)

        grid = QGridLayout()
        self.pack_buttons = {}
        for col, (name, (label, description, icon)) in enumerate(PACKS.items()):
            card = Panel()
            button = QPushButton(f"{icon}  {label}")
            button.setToolTip(description)
            button.setCheckable(True)
            button.clicked.connect(lambda _=False, p=name: self.set_pack(p))
            self.pack_buttons[name] = button
            card.box.addWidget(button)
            card.box.addStretch()
            grid.addWidget(card, 0, col)
        root.addLayout(grid)

        preview = Panel()
        preview.add_title("TRY IT")
        self.preview = TypingPad()
        preview.box.addWidget(self.preview)
        root.addWidget(preview, 1)

        controls = Panel()
        controls.add_title("LISTENING")
        row = QHBoxLayout()
        self.enable_btn = QPushButton("Enable key sounds")
        self.enable_btn.setCheckable(True)
        self.enable_btn.setProperty("accent", "true")
        self.enable_btn.toggled.connect(self._toggle)
        row.addWidget(self.enable_btn)
        row.addWidget(QLabel("Volume"))
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(45)
        self.volume.setFixedWidth(150)
        self.volume.valueChanged.connect(self._volume_changed)
        row.addWidget(self.volume)
        self.volume_text = QLabel("45%")
        row.addWidget(self.volume_text)
        row.addStretch()
        self.accent = QCheckBox("Special Enter sounds")
        self.accent.setChecked(True)
        row.addWidget(self.accent)
        controls.box.addLayout(row)

        input_row = QHBoxLayout()
        input_row.addWidget(QLabel("Listen"))
        self.scope = QComboBox()
        self.scope.addItem("Inside FreeAlien", "app")
        self.scope.addItem("Everywhere", "global")
        self.scope.setCurrentIndex(0)
        input_row.addWidget(self.scope)
        self.devices = QComboBox()
        self.devices.addItem("Automatic · all connected typing keyboards", None)
        for device in keyboard_devices():
            self.devices.addItem(f"{device.name} · {device.path}", device)
        input_row.addWidget(self.devices, 1)
        controls.box.addLayout(input_row)
        self.input_note = QLabel("")
        self.input_note.setWordWrap(True)
        self.input_note.setObjectName("Hint")
        controls.box.addWidget(self.input_note)
        self.capture_note = QLabel("")
        self.capture_note.setWordWrap(True)
        self.capture_note.setObjectName("Hint")
        controls.box.addWidget(self.capture_note)
        self.status = QLabel("OFF")
        self.status.setWordWrap(True)
        controls.box.addWidget(self.status)
        root.addWidget(controls)
        self.scope.currentIndexChanged.connect(self._input_changed)
        self.devices.currentIndexChanged.connect(self._input_changed)
        self.set_pack("gaming")
        self._input_changed()

    def set_pack(self, pack):
        self.pack = pack
        self.engine.silence()
        for name, button in self.pack_buttons.items():
            button.setChecked(name == pack)
        self.preview.setText(f"{PACKS[pack][2]}  {PACKS[pack][0]}\nClick here and type")

    def _volume_changed(self, value):
        self.engine.volume = value / 100
        self.volume_text.setText(f"{value}%")
        if not value: self.engine.silence()

    def _input_changed(self, *_):
        global_mode = self.scope.currentData() == "global"
        native = global_mode and not GlobalKeyboard.uses_x11()
        if global_mode:
            self.preview.setText("Click here and type to try your pack")
        self.devices.setVisible(native)
        note = (
            "Plays on key presses across apps. Enable handles one-time keyboard access if needed. "
            "Access persists after muting or quitting until removed in the uninstaller; "
            "other apps in your session can also read this keyboard, including password-field presses. "
            "FreeAlien does not save typed text or display background key names."
            if native else "Plays on key presses across apps, including password fields; "
            "no typed text is saved or background key names displayed."
            if global_mode else "Plays while FreeAlien is focused. Choose Everywhere for background sounds.")
        self.input_note.setText("Includes password fields · no typed text saved" if global_mode else "Only while FreeAlien is focused")
        self.input_note.setToolTip(note)
        if self.enabled:
            self._toggle(True)

    def _toggle(self, enabled, allow_setup=True):
        if self._setup_process is not None: return
        self.listener.stop()
        self.engine.silence()
        self._app_held.clear()
        self.enabled = enabled
        if enabled and self.scope.currentData() == "global":
            try:
                self.listener.start(self.devices.currentData())
                if self.listener.denied and allow_setup:
                    self._setup_access()
                    return
            except OSError as exc:
                if allow_setup and not GlobalKeyboard.uses_x11() and self._selected_devices():
                    self._setup_access()
                else:
                    self._fail(str(exc))
                return
            self.preview.setText("Playing across apps")
        self.enable_btn.setText("Mute key sounds" if enabled else "Enable key sounds")
        self.capture_note.setText(self.listener.description() if enabled and
                                  self.scope.currentData() == "global" and not GlobalKeyboard.uses_x11() else "")
        self.status.setText(("ON · Across apps"
                             if self.scope.currentData() == "global" else
                             "ON · Inside FreeAlien") if enabled else "OFF")

    def _fail(self, message):
        self.enable_btn.setChecked(False)
        self.enabled = False
        self.listener.stop()
        self.engine.silence()
        self.status.setText(message)

    def _capture_changed(self, message):
        if self.enabled: self.capture_note.setText(message)

    def _selected_devices(self):
        device = self.devices.currentData()
        return [device] if device is not None else keyboard_devices()

    def _setup_access(self):
        devices = self._selected_devices()
        if not devices or self._setup_process is not None: return
        pkexec = shutil.which("pkexec")
        if not pkexec:
            self._fail("One-time setup needs polkit (pkexec). Install it, then enable sounds again.")
            return
        installer = Path(__file__).resolve().parents[2] / "packaging/install_sound_input.py"
        process = QProcess(self)
        self._setup_process = process
        self.listener.stop()
        self.enabled = False
        self.enable_btn.setEnabled(False)
        self.enable_btn.setText("Setting up…")
        self.devices.setEnabled(False)
        self.scope.setEnabled(False)
        process.finished.connect(self._setup_finished)
        process.errorOccurred.connect(self._setup_error)
        self.status.setText("Waiting for administrator authentication for one-time keyboard access setup…")
        arguments = ["/usr/bin/python3", "-I", str(installer)]
        for device in devices: arguments.extend(["--device", Path(device.path).name])
        process.start(pkexec, arguments)

    def _setup_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self._finish_setup(False, "Could not start administrator authentication.")

    def _setup_finished(self, code, status):
        process = self._setup_process
        if process is None: return
        message = bytes(process.readAllStandardError()).decode(errors="replace").strip()
        success = code == 0 and status == QProcess.ExitStatus.NormalExit
        self._finish_setup(success, message or "Keyboard access setup was cancelled or failed.")

    def _finish_setup(self, success, message):
        process, self._setup_process = self._setup_process, None
        if process is not None: process.deleteLater()
        self.devices.setEnabled(True)
        self.scope.setEnabled(True)
        self.enable_btn.setEnabled(True)
        if success:
            self._toggle(True, allow_setup=False)
        else:
            self._fail(message)

    def _play(self, name):
        if self.volume.value() == 0: return
        role = key_role(name)
        if role == "enter" and not self.accent.isChecked(): role = "normal"
        variant = self.picker.next(self.pack, role)
        try:
            column = layout.CELLS[layout.by_name(name)][0]
            pan = (column / 15 * 2 - 1) * 0.45
        except KeyError:
            pan = 0
        self.engine.play(self.pack, name, variant, self.accent.isChecked(), pan)

    def _global_press(self, name):
        if self.enabled and self.scope.currentData() == "global":
            from ..sounds.input import sound_press
            self._play(sound_press(name))

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.ApplicationDeactivate, QEvent.Type.WindowDeactivate):
            self._app_held.clear()
        if event.type() == QEvent.Type.KeyRelease and not event.isAutoRepeat():
            self._app_held.discard(event.nativeScanCode() or event.key())
        if (event.type() == QEvent.Type.KeyPress and not event.isAutoRepeat()
                and self.window().isActiveWindow()
                and (not self.enabled and watched is self.preview or
                     self.enabled and self.scope.currentData() == "app")):
            identity = event.nativeScanCode() or event.key()
            if identity not in self._app_held:
                self._app_held.add(identity)
                self._play(qt_key_name(event.key()))
        return super().eventFilter(watched, event)

    def close(self):
        if self._setup_process is not None:
            self._setup_process.disconnect()
            self._setup_process.kill()
            self._setup_process.deleteLater()
            self._setup_process = None
        self.enabled = False
        self.listener.stop()
        self.engine.close()
        app = QApplication.instance()
        if app is not None: app.removeEventFilter(self)
        return super().close()
