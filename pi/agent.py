#!/usr/bin/env python3
"""stdin protocol — mouse cmds ack first for low latency."""
import sys
from hid_type import HidTyper

t = HidTyper(delay=0.004)
sys.stdout.write("OK\n")
sys.stdout.flush()

def ack():
    sys.stdout.write(".\n")
    sys.stdout.flush()

for line in sys.stdin:
    line = line.rstrip("\n")
    if not line:
        continue
    cmd, _, arg = line.partition(":")
    # mouse: ack immediately so client never blocks on RTT-after-work
    if cmd == "M":
        ack()
        parts = [int(x or 0) for x in (arg.split(",") + ["0", "0", "0"])[:3]]
        t.mouse_move(parts[0], parts[1], parts[2])
        continue
    if cmd == "C":
        ack()
        t.mouse_click(arg or "left")
        continue
    if cmd == "P":
        ack()
        t.mouse_down(arg or "left")
        continue
    if cmd == "R":
        ack()
        t.mouse_up(arg or "left")
        continue
    if cmd == "T":
        t.type_text(arg.replace("\\n", "\n").replace("\\t", "\t"))
    elif cmd == "B":
        t.backspace(int(arg or "1"))
    elif cmd == "E":
        t.type_char("\n")
    elif cmd == "D":
        t.key_down(int(arg, 0))
    elif cmd == "U":
        t.key_up(int(arg, 0))
    elif cmd == "X":
        t.release_all()
    elif cmd == "Q":
        break
    else:
        continue
    ack()
