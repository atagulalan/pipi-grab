#!/usr/bin/env python3
"""WiFi SSH / Bluetooth RFCOMM transports → Pi HID agent."""
from __future__ import annotations

import shutil
import socket
import subprocess
import threading

from envutil import getenv, load_dotenv, require

load_dotenv()

HOST = getenv("PIPI_HOST")
USER = getenv("PIPI_USER")
PASS = getenv("PIPI_PASS")
BT_ADDR = getenv("PIPI_BT")
BT_CHANNEL = int(getenv("PIPI_BT_CH", "1") or "1")
REMOTE = getenv(
    "PIPI_REMOTE",
    "cd ~/pi-hid/webui && ../hid-venv/bin/python -u agent.py",
)
DEFAULT_MODE = getenv("PIPI_MODE", "wifi").lower() or "wifi"


class BaseTransport:
    def start(self) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError

    @property
    def ok(self) -> bool:
        raise NotImplementedError

    def send(self, line: str) -> None:
        raise NotImplementedError

    def send_mouse(self, dx: int, dy: int, w: int = 0) -> None:
        raise NotImplementedError


class SshTransport(BaseTransport):
    def __init__(self) -> None:
        self._proc: subprocess.Popen[str] | None = None
        self._ready = False
        self._wlock = threading.Lock()
        self._pending_m = [0, 0, 0]
        self._m_sched = False
        self._m_lock = threading.Lock()

    def start(self) -> None:
        if shutil.which("sshpass") is None:
            raise RuntimeError("sshpass required")
        host, user, password = require("PIPI_HOST"), require("PIPI_USER"), require("PIPI_PASS")
        self._ready = False
        self._proc = subprocess.Popen(
            [
                "sshpass", "-p", password, "ssh",
                "-o", "StrictHostKeyChecking=no",
                "-o", "UserKnownHostsFile=/dev/null",
                "-o", "ServerAliveInterval=15",
                "-o", "TCPKeepAlive=yes",
                "-o", "Compression=no",
                f"{user}@{host}", REMOTE,
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        assert self._proc.stdout is not None
        line = self._proc.stdout.readline().strip()
        if line != "OK":
            err = self._proc.stderr.read() if self._proc.stderr else ""
            self.stop()
            raise RuntimeError(f"ssh agent failed: {line!r} {err}")
        self._ready = True
        threading.Thread(target=self._drain, daemon=True).start()

    def stop(self) -> None:
        self._ready = False
        p = self._proc
        self._proc = None
        if p and p.poll() is None:
            try:
                if p.stdin:
                    p.stdin.write("Q\n")
                    p.stdin.flush()
            except Exception:
                pass
            try:
                p.terminate()
            except Exception:
                pass

    def _drain(self) -> None:
        assert self._proc and self._proc.stdout
        try:
            for _ in self._proc.stdout:
                pass
        except Exception:
            pass
        self._ready = False

    @property
    def ok(self) -> bool:
        return self._ready and self._proc is not None and self._proc.poll() is None

    def _write(self, line: str) -> None:
        if not self.ok:
            self.start()
        assert self._proc and self._proc.stdin
        with self._wlock:
            self._proc.stdin.write(line + "\n")
            self._proc.stdin.flush()

    def send(self, line: str) -> None:
        self._write(line)

    def send_mouse(self, dx: int, dy: int, w: int = 0) -> None:
        with self._m_lock:
            self._pending_m[0] += dx
            self._pending_m[1] += dy
            self._pending_m[2] += w
            if self._m_sched:
                return
            self._m_sched = True
        threading.Timer(0.008, self._flush_mouse).start()

    def _flush_mouse(self) -> None:
        with self._m_lock:
            dx, dy, w = self._pending_m
            self._pending_m = [0, 0, 0]
            self._m_sched = False
        if dx or dy or w:
            self._write(f"M:{dx},{dy},{w}")


class BtTransport(BaseTransport):
    def __init__(self) -> None:
        self._sock: socket.socket | None = None
        self._ready = False
        self._wlock = threading.Lock()
        self._pending_m = [0, 0, 0]
        self._m_sched = False
        self._m_lock = threading.Lock()
        self._err: str | None = None

    def start(self) -> None:
        self.stop()
        self._err = None
        self._ready = False
        addr = require("PIPI_BT")
        channel = int(getenv("PIPI_BT_CH", "1") or "1")
        s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
        s.settimeout(12)
        try:
            s.connect((addr, channel))
        except OSError as e:
            s.close()
            self._err = str(e)
            raise RuntimeError(f"bt connect {addr} ch{channel}: {e}") from e
        s.settimeout(None)
        buf = b""
        while b"\n" not in buf:
            chunk = s.recv(64)
            if not chunk:
                s.close()
                raise RuntimeError("bt: closed before OK")
            buf += chunk
        line, rest = buf.split(b"\n", 1)
        if line.strip() != b"OK":
            s.close()
            raise RuntimeError(f"bt agent failed: {line!r}")
        self._sock = s
        self._ready = True
        threading.Thread(target=self._drain, args=(rest,), daemon=True).start()

    def stop(self) -> None:
        self._ready = False
        s = self._sock
        self._sock = None
        if s:
            try:
                s.sendall(b"Q\n")
            except Exception:
                pass
            try:
                s.close()
            except Exception:
                pass

    def _drain(self, rest: bytes = b"") -> None:
        s = self._sock
        if not s:
            return
        try:
            while True:
                if not s.recv(256):
                    break
        except Exception:
            pass
        self._ready = False

    @property
    def ok(self) -> bool:
        return self._ready and self._sock is not None

    def _write(self, line: str) -> None:
        if not self.ok:
            self.start()
        assert self._sock is not None
        with self._wlock:
            self._sock.sendall((line + "\n").encode())

    def send(self, line: str) -> None:
        self._write(line)

    def send_mouse(self, dx: int, dy: int, w: int = 0) -> None:
        with self._m_lock:
            self._pending_m[0] += dx
            self._pending_m[1] += dy
            self._pending_m[2] += w
            if self._m_sched:
                return
            self._m_sched = True
        threading.Timer(0.004, self._flush_mouse).start()

    def _flush_mouse(self) -> None:
        with self._m_lock:
            dx, dy, w = self._pending_m
            self._pending_m = [0, 0, 0]
            self._m_sched = False
        if dx or dy or w:
            self._write(f"M:{dx},{dy},{w}")


class Router:
    def __init__(self, mode: str | None = None) -> None:
        m = (mode or DEFAULT_MODE).lower()
        self.mode = "bt" if m in ("bt", "bluetooth") else "wifi"
        self._ssh = SshTransport()
        self._bt = BtTransport()
        self._lock = threading.Lock()
        self.last_error: str | None = None

    @property
    def t(self) -> BaseTransport:
        return self._bt if self.mode == "bt" else self._ssh

    @property
    def ok(self) -> bool:
        return self.t.ok

    def start(self) -> None:
        with self._lock:
            self.t.start()

    def set_mode(self, mode: str) -> None:
        mode = "bt" if mode in ("bt", "bluetooth") else "wifi"
        with self._lock:
            if mode == self.mode and self.t.ok:
                return
            self._ssh.stop()
            self._bt.stop()
            self.mode = mode
            try:
                self.t.start()
                self.last_error = None
            except Exception as e:
                self.last_error = str(e)
                raise

    def send(self, line: str) -> None:
        self.t.send(line)

    def send_mouse(self, dx: int, dy: int, w: int = 0) -> None:
        self.t.send_mouse(dx, dy, w)
