"""HID keyboard + mouse helper."""
from __future__ import annotations

import fcntl
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path.home() / "pi-hid" / "python"))

from adafruit_hid.keycode import Keycode
from adafruit_hid.keyboard import Keyboard
from devices import HIDDeviceKeyboard

CHAR_MAP: dict[str, tuple] = {}
for c, k in [
    ("a", Keycode.A), ("b", Keycode.B), ("c", Keycode.C), ("d", Keycode.D),
    ("e", Keycode.E), ("f", Keycode.F), ("g", Keycode.G), ("h", Keycode.H),
    ("i", Keycode.I), ("j", Keycode.J), ("k", Keycode.K), ("l", Keycode.L),
    ("m", Keycode.M), ("n", Keycode.N), ("o", Keycode.O), ("p", Keycode.P),
    ("q", Keycode.Q), ("r", Keycode.R), ("s", Keycode.S), ("t", Keycode.T),
    ("u", Keycode.U), ("v", Keycode.V), ("w", Keycode.W), ("x", Keycode.X),
    ("y", Keycode.Y), ("z", Keycode.Z),
]:
    CHAR_MAP[c] = (k, False)
    CHAR_MAP[c.upper()] = (k, True)
for c, k in [
    ("1", Keycode.ONE), ("2", Keycode.TWO), ("3", Keycode.THREE), ("4", Keycode.FOUR),
    ("5", Keycode.FIVE), ("6", Keycode.SIX), ("7", Keycode.SEVEN), ("8", Keycode.EIGHT),
    ("9", Keycode.NINE), ("0", Keycode.ZERO),
]:
    CHAR_MAP[c] = (k, False)
CHAR_MAP.update({
    " ": (Keycode.SPACE, False), "\n": (Keycode.ENTER, False), "\t": (Keycode.TAB, False),
    "-": (Keycode.MINUS, False), "_": (Keycode.MINUS, True), "=": (Keycode.EQUALS, False),
    "+": (Keycode.EQUALS, True), "[": (Keycode.LEFT_BRACKET, False), "{": (Keycode.LEFT_BRACKET, True),
    "]": (Keycode.RIGHT_BRACKET, False), "}": (Keycode.RIGHT_BRACKET, True),
    "\\": (Keycode.BACKSLASH, False), "|": (Keycode.BACKSLASH, True),
    ";": (Keycode.SEMICOLON, False), ":": (Keycode.SEMICOLON, True),
    "'": (Keycode.QUOTE, False), '"': (Keycode.QUOTE, True),
    ",": (Keycode.COMMA, False), "<": (Keycode.COMMA, True),
    ".": (Keycode.PERIOD, False), ">": (Keycode.PERIOD, True),
    "/": (Keycode.FORWARD_SLASH, False), "?": (Keycode.FORWARD_SLASH, True),
    "`": (Keycode.GRAVE_ACCENT, False), "~": (Keycode.GRAVE_ACCENT, True),
    "!": (Keycode.ONE, True), "@": (Keycode.TWO, True), "#": (Keycode.THREE, True),
    "$": (Keycode.FOUR, True), "%": (Keycode.FIVE, True), "^": (Keycode.SIX, True),
    "&": (Keycode.SEVEN, True), "*": (Keycode.EIGHT, True), "(": (Keycode.NINE, True),
    ")": (Keycode.ZERO, True),
})
TR_FALLBACK = {
    "ç": "c", "Ç": "C", "ğ": "g", "Ğ": "G", "ı": "i", "İ": "I",
    "ö": "o", "Ö": "O", "ş": "s", "Ş": "S", "ü": "u", "Ü": "U",
}


def _nonblock(f) -> None:
    try:
        fd = f.fileno()
        fl = fcntl.fcntl(fd, fcntl.F_GETFL)
        fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)
    except Exception:
        pass


def _write_nb(f, data: bytes) -> None:
    """Motion/wheel: drop if host isn't polling (avoid wedging BT/SSH)."""
    try:
        f.write(data)
    except (BlockingIOError, OSError):
        pass


def _write_btn(f, data: bytes, budget: float = 0.02) -> bool:
    """Button state: retry briefly — never silently drop press/release."""
    deadline = time.monotonic() + budget
    while True:
        try:
            f.write(data)
            return True
        except BlockingIOError:
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.001)
        except OSError:
            return False


class HidTyper:
    def __init__(self, delay: float = 0.008):
        self.delay = delay
        # Keyboard: blocking writes — never drop Shift+key chords
        self._kbd_dev = HIDDeviceKeyboard()
        self._kbd = Keyboard(self._kbd_dev)
        # Mouse: non-blocking so a stalled host can't wedge BT
        self._hidg_mouse = open("/dev/hidg1", "wb", buffering=0)
        _nonblock(self._hidg_mouse)
        self._mbtn = 0

    def tap(self, *keys):
        self._kbd.press(*keys)
        time.sleep(self.delay)
        self._kbd.release_all()
        time.sleep(self.delay)

    def backspace(self, n: int = 1):
        for _ in range(max(0, n)):
            self.tap(Keycode.BACKSPACE)

    def type_char(self, ch: str) -> bool:
        ch = TR_FALLBACK.get(ch, ch)
        if ch not in CHAR_MAP:
            return False
        key, shift = CHAR_MAP[ch]
        if shift:
            self.tap(Keycode.SHIFT, key)
        else:
            self.tap(key)
        return True

    def type_text(self, text: str):
        for ch in text:
            self.type_char(ch)

    def key_down(self, *codes: int):
        if not codes:
            return
        self._kbd.press(*codes)
        # Modifier-only report needs a beat before the next key joins the chord
        if len(codes) == 1 and 0xE0 <= int(codes[0]) <= 0xE7:
            time.sleep(0.008)

    def key_up(self, *codes: int):
        if codes:
            self._kbd.release(*codes)

    def release_all(self):
        self._kbd.release_all()

    def _mreport(self, dx=0, dy=0, wheel=0):
        def clamp(v):
            return max(-127, min(127, int(v)))

        while dx or dy or wheel:
            sx, sy, sw = clamp(dx), clamp(dy), clamp(wheel)
            _write_nb(
                self._hidg_mouse,
                bytes([
                    self._mbtn & 0x07,
                    sx & 0xFF,
                    sy & 0xFF,
                    sw & 0xFF,
                ]),
            )
            dx -= sx
            dy -= sy
            wheel -= sw

    def mouse_move(self, dx: int, dy: int, wheel: int = 0):
        self._mreport(dx, dy, wheel)

    def _breport(self) -> bool:
        """Send a zero-motion report carrying current button bits."""
        return _write_btn(
            self._hidg_mouse,
            bytes([self._mbtn & 0x07, 0, 0, 0]),
        )

    def mouse_click(self, button: str = "left"):
        self.mouse_down(button)
        self.mouse_up(button)

    def mouse_down(self, button: str = "left"):
        bit = {"left": 1, "right": 2, "middle": 4}.get(button, 1)
        self._mbtn |= bit
        if self._breport():
            # Let host sample button-down before an immediate up (same as mod chord)
            time.sleep(0.008)

    def mouse_up(self, button: str = "left"):
        bit = {"left": 1, "right": 2, "middle": 4}.get(button, 1)
        self._mbtn &= ~bit
        self._breport()
