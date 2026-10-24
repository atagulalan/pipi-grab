<img src="https://raw.githubusercontent.com/atagulalan/pipi-grab/main/docs/banner-light.svg#gh-light-mode-only" width="50%" alt="pipi.grab — Pi Zero W USB HID keyboard & mouse over Wi-Fi / Bluetooth"/>
<img src="https://raw.githubusercontent.com/atagulalan/pipi-grab/main/docs/banner-dark.svg#gh-dark-mode-only" width="50%" alt="pipi.grab — Pi Zero W USB HID keyboard & mouse over Wi-Fi / Bluetooth"/>

Control a **Raspberry Pi Zero W** that acts as a USB keyboard/mouse (HID gadget) for another device (Mac, iPad, PC). Your Linux PC runs **pipi.grab** (native GTK + `evdev`) and talks to the Pi over **Wi‑Fi SSH** or **Bluetooth RFCOMM**; the Pi injects keystrokes and mouse moves into the USB host.

```
[PC: pipi.grab]
        │  Wi‑Fi SSH  or  Bluetooth RFCOMM
        ▼
[Pi Zero W: agent / bt_server]
        │  USB OTG HID (/dev/hidg0, hidg1)
        ▼
[Target: Mac / iPad / …]
```

## What’s in this repo

| File | Role |
|------|------|
| `grab_gui.py` | Native GTK window — exclusive keyboard/mouse grab via `evdev` |
| `grab_app.py` | Grab core (devices, HID map, grabber) used by the GUI |
| `transport.py` | Shared SSH + Bluetooth transports |
| `bt_server.py` / `pi/` | **Pi bundle** — HID gadget, agent, BT server (Mac-friendly mouse) |
| `ensure_pi.sh` | Over SSH: check Pi stack; install/refresh from `pi/` if missing |
| `run.sh` | Runs `ensure_pi.sh` then `grab_gui.py` in your graphical session |
| `.env.example` | Template for secrets / host settings |

Secrets live in **`.env`** (gitignored). Copy from `.env.example`.

---

## 1. Flash the Pi

Hardware: **Raspberry Pi Zero W** (has Wi‑Fi + Bluetooth). Use a **data-capable** micro‑USB cable in the **inner USB (data)** port when talking HID to a host — not the outer PWR-only port alone if you need gadget data.

1. Flash **Raspberry Pi OS Lite (Bookworm)** with [Raspberry Pi Imager](https://www.raspberrypi.com/software/).
2. In Imager → OS customisation:
   - Hostname (e.g. `pipi`)
   - Username / password
   - **Enable SSH**
   - Wi‑Fi: use a **2.4 GHz** SSID (Zero W has **no 5 GHz**)
   - Locale / keyboard / timezone
3. Boot, then confirm from your PC:

```bash
ping pipi.local
ssh YOUR_USER@pipi.local
```

If `pipi.local` fails, find the IP on your router or with `nmap` / ARP, then set `PIPI_HOST` to that IP.

---

## 2. Pi HID stack (auto over Wi‑Fi)

This repo ships the working Pi files under **`pi/`** (Mac-friendly relative mouse: 5-byte report, wheel + AC Pan, `subclass=0` — boot-protocol mice drop scroll on macOS).

With `PIPI_HOST` / `PIPI_USER` / `PIPI_PASS` set, from the PC:

```bash
./ensure_pi.sh
```

That SSHes in, checks `/dev/hidg*`, mouse `report_length=5` / `subclass=0`, and `/etc/pipi-grab.ver`. If anything’s wrong it uploads `pi/` and runs `pi/install_remote.sh` (clones [pi-hid](https://github.com/thiagofeijodev/pi-hid) if needed, venv, overlays, systemd, BT server).

`./run.sh` calls `ensure_pi.sh` first. Skip with `PIPI_SKIP_ENSURE=1`.

First-time `dtoverlay=dwc2` may need a **Pi reboot**, then `./ensure_pi.sh` again. Plug the Pi’s **data** USB into the target and check:

```bash
ls -l /dev/hidg*    # on the Pi — expect hidg0 + hidg1
```

### Manual (same as ensure)

On the Pi you can also copy `pi/` over and `sudo bash install_remote.sh`.

SSH agent command (default `PIPI_REMOTE`):

```text
cd ~/pi-hid/webui && ../hid-venv/bin/python -u agent.py
```

### Bluetooth RFCOMM

`ensure_pi` installs `bt_server.py` + `pi-hid-bt.service`. Pair once (`bluetoothctl`), set `PIPI_BT` on the PC to the Pi MAC.

---

## 4. PC: install this project

```bash
git clone https://github.com/atagulalan/pipi-grab.git
cd pipi-grab
cp .env.example .env
# edit .env — host, user, password, BT MAC

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# GTK GUI (Arch / CachyOS-ish)
sudo pacman -S python-gobject gtk4 python-cairo   # or distro equivalents

# SSH password auth helper (Wi‑Fi mode)
sudo pacman -S sshpass   # Debian/Ubuntu: apt install sshpass

# Input grab needs read access to /dev/input/event*
# Either run as a user in the `input` group, or adjust udev rules.
sudo usermod -aG input "$USER"
# log out / in after group change
```

### `.env` keys

| Variable | Required | Meaning |
|----------|----------|---------|
| `PIPI_HOST` | Wi‑Fi mode | Hostname or IP (`pipi.local` or `192.168.x.x`) |
| `PIPI_USER` | Wi‑Fi mode | SSH username |
| `PIPI_PASS` | Wi‑Fi mode | SSH password (`sshpass`) |
| `PIPI_BT` | BT mode | Pi Bluetooth MAC |
| `PIPI_BT_CH` | no | RFCOMM channel (default `1`) |
| `PIPI_MODE` | no | `wifi` or `bt` (default `wifi`) |
| `PIPI_REMOTE` | no | Remote command for SSH agent |

Never commit `.env`. Only `.env.example` goes to GitHub.

---

## 5. Run

Pi must be reachable (Wi‑Fi) and/or BT server running; USB HID plugged into the **target**.

```bash
./run.sh
# or: python3 grab_gui.py
```

- Keyboard + mouse are grabbed exclusively and forwarded to the Pi.
- Release grab: press **Win / Super** four times quickly.
- Switch Wi‑Fi ↔ Bluetooth from the GUI when both paths are set up.

---

## 6. Protocol (reference)

Lines ending with `\n` from PC → Pi agent / `bt_server.py`:

| Command | Meaning |
|---------|---------|
| `T:text` | Type UTF‑8 text (`\n` / `\t` escapes) |
| `B:n` | Backspace `n` times |
| `E` | Enter |
| `D:0x..` / `U:0x..` | Key down / up (HID usage) |
| `X` | Release all keys |
| `M:dx,dy,w` | Mouse move / wheel |
| `C:left` | Click |
| `P:` / `R:` | Mouse button down / up |
| `Q` | Quit session |

First response from the agent is `OK`.

---

## Troubleshooting

| Symptom | Check |
|---------|--------|
| No `pipi.local` | 2.4 GHz Wi‑Fi only; SSH enabled in Imager; same LAN |
| No `/dev/hidg*` | `dtoverlay=dwc2,dr_mode=peripheral`, reboot, data cable, data port |
| Target ignores keyboard | Apple hosts often need gadget VID/PID as in pi-hid defaults |
| Scroll works nowhere / Mac: click OK, wheel dead | Mouse gadget must be **non-boot** (`hid.usb1/subclass` = `0`). Boot mouse is 3 bytes — no wheel. Replug USB after changing. |
| `sshpass` / auth fail | `.env` user/pass; try `ssh USER@HOST` manually |
| BT connect fails | Pair/trust Pi first; `bt_server.py` listening; correct `PIPI_BT` |
| Grab fails / no devices | User in `input` group; not grabbing virtual devices (keyd, ydotool, …) |

---

## Security notes

- Prefer **SSH keys** long-term; password + `sshpass` is convenient but stores `PIPI_PASS` in `.env`.
- BT server may run with relaxed RFCOMM link mode for simplicity — pair only devices you trust; don’t leave discoverable forever on untrusted networks.

---

## License

Use / modify as you like for personal projects. Upstream HID stack: [thiagofeijodev/pi-hid](https://github.com/thiagofeijodev/pi-hid) (follow that project’s license).
