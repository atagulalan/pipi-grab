#!/usr/bin/env python3
"""Grab core — evdev exclusive input → Pi HID. Win×4 releases. Used by grab_gui."""
from __future__ import annotations

import select
import threading
import time

from evdev import InputDevice, ecodes, list_devices

from envutil import load_dotenv
from transport import Router

load_dotenv()
WIN_NEEDED = 4
WIN_WINDOW = 0.55

SKIP_NAME = (
    "keyd",
    "libvirtualhid",
    "vicinae",
    "virtual",
    "ydotool",
    "uinput",
)

KEY_TO_HID: dict[int, int] = {
    ecodes.KEY_A: 0x04, ecodes.KEY_B: 0x05, ecodes.KEY_C: 0x06, ecodes.KEY_D: 0x07,
    ecodes.KEY_E: 0x08, ecodes.KEY_F: 0x09, ecodes.KEY_G: 0x0A, ecodes.KEY_H: 0x0B,
    ecodes.KEY_I: 0x0C, ecodes.KEY_J: 0x0D, ecodes.KEY_K: 0x0E, ecodes.KEY_L: 0x0F,
    ecodes.KEY_M: 0x10, ecodes.KEY_N: 0x11, ecodes.KEY_O: 0x12, ecodes.KEY_P: 0x13,
    ecodes.KEY_Q: 0x14, ecodes.KEY_R: 0x15, ecodes.KEY_S: 0x16, ecodes.KEY_T: 0x17,
    ecodes.KEY_U: 0x18, ecodes.KEY_V: 0x19, ecodes.KEY_W: 0x1A, ecodes.KEY_X: 0x1B,
    ecodes.KEY_Y: 0x1C, ecodes.KEY_Z: 0x1D,
    ecodes.KEY_1: 0x1E, ecodes.KEY_2: 0x1F, ecodes.KEY_3: 0x20, ecodes.KEY_4: 0x21,
    ecodes.KEY_5: 0x22, ecodes.KEY_6: 0x23, ecodes.KEY_7: 0x24, ecodes.KEY_8: 0x25,
    ecodes.KEY_9: 0x26, ecodes.KEY_0: 0x27,
    ecodes.KEY_ENTER: 0x28, ecodes.KEY_ESC: 0x29, ecodes.KEY_BACKSPACE: 0x2A,
    ecodes.KEY_TAB: 0x2B, ecodes.KEY_SPACE: 0x2C,
    ecodes.KEY_MINUS: 0x2D, ecodes.KEY_EQUAL: 0x2E,
    ecodes.KEY_LEFTBRACE: 0x2F, ecodes.KEY_RIGHTBRACE: 0x30, ecodes.KEY_BACKSLASH: 0x31,
    ecodes.KEY_SEMICOLON: 0x33, ecodes.KEY_APOSTROPHE: 0x34, ecodes.KEY_GRAVE: 0x35,
    ecodes.KEY_COMMA: 0x36, ecodes.KEY_DOT: 0x37, ecodes.KEY_SLASH: 0x38,
    ecodes.KEY_CAPSLOCK: 0x39,
    ecodes.KEY_F1: 0x3A, ecodes.KEY_F2: 0x3B, ecodes.KEY_F3: 0x3C, ecodes.KEY_F4: 0x3D,
    ecodes.KEY_F5: 0x3E, ecodes.KEY_F6: 0x3F, ecodes.KEY_F7: 0x40, ecodes.KEY_F8: 0x41,
    ecodes.KEY_F9: 0x42, ecodes.KEY_F10: 0x43, ecodes.KEY_F11: 0x44, ecodes.KEY_F12: 0x45,
    ecodes.KEY_SYSRQ: 0x46, ecodes.KEY_SCROLLLOCK: 0x47, ecodes.KEY_PAUSE: 0x48,
    ecodes.KEY_INSERT: 0x49, ecodes.KEY_HOME: 0x4A, ecodes.KEY_PAGEUP: 0x4B,
    ecodes.KEY_DELETE: 0x4C, ecodes.KEY_END: 0x4D, ecodes.KEY_PAGEDOWN: 0x4E,
    ecodes.KEY_RIGHT: 0x4F, ecodes.KEY_LEFT: 0x50, ecodes.KEY_DOWN: 0x51, ecodes.KEY_UP: 0x52,
    ecodes.KEY_NUMLOCK: 0x53,
    ecodes.KEY_LEFTCTRL: 0xE0, ecodes.KEY_LEFTSHIFT: 0xE1, ecodes.KEY_LEFTALT: 0xE2,
    ecodes.KEY_LEFTMETA: 0xE3,
    ecodes.KEY_RIGHTCTRL: 0xE4, ecodes.KEY_RIGHTSHIFT: 0xE5, ecodes.KEY_RIGHTALT: 0xE6,
    ecodes.KEY_RIGHTMETA: 0xE7,
    ecodes.KEY_COMPOSE: 0x65,
}
META_KEYS = {ecodes.KEY_LEFTMETA, ecodes.KEY_RIGHTMETA}
BTN_MAP = {
    ecodes.BTN_LEFT: "left",
    ecodes.BTN_RIGHT: "right",
    ecodes.BTN_MIDDLE: "middle",
}


def _is_virtual(name: str) -> bool:
    n = name.lower()
    return any(s in n for s in SKIP_NAME)


def find_devices() -> list[InputDevice]:
    """Physical kb/mouse only. Compositor reads these directly; keyd virtual
    alone is not enough to lock the host on this machine."""
    found: list[InputDevice] = []
    seen: set[str] = set()
    for path in list_devices():
        try:
            dev = InputDevice(path)
        except (OSError, PermissionError):
            continue
        if _is_virtual(dev.name):
            continue
        caps = dev.capabilities(verbose=False)
        keys = caps.get(ecodes.EV_KEY, [])
        rels = caps.get(ecodes.EV_REL, [])
        is_kbd = ecodes.EV_KEY in caps and ecodes.KEY_A in keys
        is_mouse = (ecodes.EV_REL in caps and ecodes.REL_X in rels) or ecodes.BTN_LEFT in keys
        if not (is_kbd or is_mouse):
            continue
        if path in seen:
            continue
        seen.add(path)
        found.append(dev)
    return found


class Grabber:
    def __init__(self, router: Router) -> None:
        self.router = router
        self._lock = threading.Lock()
        self._active = False
        self._devs: list[InputDevice] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._win_taps: list[float] = []
        self._wheel_hr = 0  # REL_WHEEL_HI_RES accumulator (120 = one notch)
        self._wheel_hires = False  # True if any grabbed device exposes HI_RES
        self.last_error: str | None = None
        self.device_names: list[str] = []
        self._shift_held: set[int] = set()  # HID mods down — for chord pacing
        self._last_mod_down_mono = 0.0

    @property
    def active(self) -> bool:
        return self._active

    def grab(self) -> None:
        with self._lock:
            if self._active:
                return
            if not self.router.ok:
                self.router.start()
            devs = find_devices()
            if not devs:
                raise RuntimeError("no keyboard/mouse devices found")
            grabbed: list[InputDevice] = []
            errors: list[str] = []
            for d in devs:
                try:
                    d.grab()
                    grabbed.append(d)
                except OSError as e:
                    errors.append(f"{d.name}: {e}")
                    try:
                        d.close()
                    except OSError:
                        pass
            if not grabbed:
                raise RuntimeError("grab failed on all devices: " + "; ".join(errors))
            if errors:
                print(f"grab partial skips: {errors}", flush=True)
            self._devs = grabbed
            self.device_names = [d.name for d in grabbed]
            self._wheel_hr = 0
            self._wheel_hires = any(
                ecodes.REL_WHEEL_HI_RES in (d.capabilities(False).get(ecodes.EV_REL) or [])
                for d in grabbed
            )
            self._stop.clear()
            self._win_taps.clear()
            self._active = True
            self.last_error = None
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
            print(f"grabbed: {self.device_names} hires_wheel={self._wheel_hires}", flush=True)

    def ungrab(self) -> None:
        with self._lock:
            self._ungrab_locked()

    def _ungrab_locked(self) -> None:
        if not self._active and not self._devs:
            return
        self._stop.set()
        self._active = False
        for d in self._devs:
            try:
                d.ungrab()
            except OSError:
                pass
            try:
                d.close()
            except OSError:
                pass
        self._devs = []
        self.device_names = []
        try:
            self.router.send("X")
        except Exception:
            pass
        print("ungrabbed", flush=True)

    def _note_win(self) -> bool:
        now = time.monotonic()
        if self._win_taps and now - self._win_taps[-1] > WIN_WINDOW:
            self._win_taps.clear()
        self._win_taps.append(now)
        self._win_taps = [t for t in self._win_taps if now - t <= WIN_WINDOW * WIN_NEEDED]
        if len(self._win_taps) >= WIN_NEEDED:
            self._win_taps.clear()
            return True
        return False

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                devs = list(self._devs)
                if not devs:
                    break
                r, _, _ = select.select(devs, [], [], 0.25)
                for dev in r:
                    try:
                        for event in dev.read():
                            try:
                                self._handle(event, getattr(dev, "name", "?"))
                            except Exception as e:
                                print(f"grab handle err: {e}", flush=True)
                    except (OSError, BlockingIOError):
                        continue
        finally:
            with self._lock:
                if self._active:
                    self._ungrab_locked()

    def _emit_wheel(self, notches: int) -> None:
        if notches:
            self.router.send_wheel(int(notches))

    def _handle(self, event, dev_name: str = "?") -> None:
        if event.type == ecodes.EV_KEY:
            btn = BTN_MAP.get(event.code)
            if btn is not None:
                if event.value == 1:  # press
                    self.router.send(f"P:{btn}")
                elif event.value == 0:  # release
                    self.router.send(f"R:{btn}")
                return

            hid = KEY_TO_HID.get(event.code)
            if hid is None:
                return
            if event.value not in (0, 1):
                return

            # Track modifiers for chord pacing (TR "=" = Shift+0 arrives ~2ms apart)
            if event.code in (ecodes.KEY_LEFTSHIFT, ecodes.KEY_RIGHTSHIFT):
                if event.value == 1:
                    self._shift_held.add(hid)
                    self.router.send(f"D:{hid}")
                    self._last_mod_down_mono = time.monotonic()
                else:
                    self._shift_held.discard(hid)
                    self.router.send(f"U:{hid}")
                return

            # Win/Meta: still forwarded; ×4 also unlocks grab
            unlock = False
            if event.code in META_KEYS and event.value == 1:
                unlock = self._note_win()

            if event.value == 1:
                # Give Mac time to see modifier report before the key (was ~2ms → flaky)
                if self._shift_held:
                    elapsed = time.monotonic() - self._last_mod_down_mono
                    wait = 0.02 - elapsed
                    if wait > 0:
                        time.sleep(wait)
                self.router.send(f"D:{hid}")
            else:
                self.router.send(f"U:{hid}")

            if unlock:
                with self._lock:
                    self._ungrab_locked()
            return

        if event.type == ecodes.EV_REL:
            if event.code == ecodes.REL_X:
                self.router.send_mouse(int(event.value), 0, 0)
            elif event.code == ecodes.REL_Y:
                self.router.send_mouse(0, int(event.value), 0)
            elif event.code == ecodes.REL_WHEEL_HI_RES:
                # 120 units = one detent; prefer this over legacy REL_WHEEL
                self._wheel_hr += int(event.value)
                notches = int(self._wheel_hr / 120)  # trunc toward 0
                if notches:
                    self._wheel_hr -= notches * 120
                    self._emit_wheel(notches)
            elif event.code == ecodes.REL_WHEEL:
                # Legacy notches — skip when HI_RES is in use (avoids double scroll)
                if not self._wheel_hires and event.value:
                    self._emit_wheel(int(event.value))
            elif event.code == ecodes.REL_HWHEEL_HI_RES:
                pass  # horizontal wheel unused by HID report
            elif event.code == ecodes.REL_HWHEEL:
                pass


router = Router()
grabber = Grabber(router)
