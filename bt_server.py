#!/usr/bin/env python3
"""RFCOMM server — same line protocol as SSH agent.py"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time

sys.path.insert(0, os.path.expanduser("~/pi-hid/webui"))
from hid_type import HidTyper  # noqa: E402

CHANNEL = 1
BACKLOG = 1
SOL_RFCOMM = 18
RFCOMM_LM = 3  # link mode — 0 = no auth/encrypt required


def advertise_spp() -> None:
    subprocess.run(["sdptool", "del", "SP"], capture_output=True)
    subprocess.run(
        ["sdptool", "add", f"--channel={CHANNEL}", "SP"],
        capture_output=True,
    )


def handle(conn: socket.socket, t: HidTyper) -> None:
    def send(s: str) -> None:
        conn.sendall((s + "\n").encode())

    def ack() -> None:
        send(".")

    send("OK")
    buf = b""
    while True:
        chunk = conn.recv(256)
        if not chunk:
            break
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            line_s = line.decode(errors="ignore").rstrip("\r")
            if not line_s:
                continue
            cmd, _, arg = line_s.partition(":")
            if cmd == "M":
                ack()
                parts = [int(x or 0) for x in (arg.split(",") + ["0", "0", "0"])[:3]]
                t.mouse_move(parts[0], parts[1], parts[2])
            elif cmd == "C":
                ack()
                t.mouse_click(arg or "left")
            elif cmd == "P":
                ack()
                t.mouse_down(arg or "left")
            elif cmd == "R":
                ack()
                t.mouse_up(arg or "left")
            elif cmd == "T":
                t.type_text(arg.replace("\\n", "\n").replace("\\t", "\t"))
                ack()
            elif cmd == "B":
                t.backspace(int(arg or "1"))
                ack()
            elif cmd == "E":
                t.type_char("\n")
                ack()
            elif cmd == "D":
                t.key_down(int(arg, 0))
                ack()
            elif cmd == "U":
                t.key_up(int(arg, 0))
                ack()
            elif cmd == "X":
                t.release_all()
                ack()
            elif cmd == "Q":
                ack()
                return


def main() -> None:
    subprocess.run(["rfkill", "unblock", "bluetooth"], capture_output=True)
    subprocess.run(["hciconfig", "hci0", "up"], capture_output=True)
    subprocess.run(["bluetoothctl", "power", "on"], capture_output=True)
    subprocess.run(["bluetoothctl", "pairable", "on"], capture_output=True)
    subprocess.run(["bluetoothctl", "discoverable", "on"], capture_output=True)
    subprocess.run(["bluetoothctl", "discoverable-timeout", "0"], capture_output=True)
    subprocess.run(["hciconfig", "hci0", "piscan"], capture_output=True)
    advertise_spp()

    mac = subprocess.check_output(["hcitool", "dev"], text=True)
    addr = None
    for line in mac.splitlines():
        parts = line.split()
        if len(parts) >= 2 and ":" in parts[-1]:
            addr = parts[-1]
            break
    if not addr:
        raise RuntimeError("no bluetooth adapter address")

    t = HidTyper(delay=0.004)
    srv = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        srv.setsockopt(SOL_RFCOMM, RFCOMM_LM, 0)
    except OSError as e:
        print(f"RFCOMM_LM warn: {e}", flush=True)
    srv.bind((addr, CHANNEL))
    srv.listen(BACKLOG)
    print(f"RFCOMM listening {addr} channel={CHANNEL} (insecure LM)", flush=True)

    while True:
        try:
            advertise_spp()
            conn, caddr = srv.accept()
            print(f"client {caddr}", flush=True)
            try:
                handle(conn, t)
            except Exception as e:
                print(f"session err: {e}", flush=True)
            finally:
                try:
                    conn.close()
                except Exception:
                    pass
                try:
                    t.release_all()
                except Exception:
                    pass
                print("client gone", flush=True)
        except Exception as e:
            print(f"accept err: {e}", flush=True)
            time.sleep(1)


if __name__ == "__main__":
    main()
