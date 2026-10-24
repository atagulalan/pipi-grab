# pipi-type

<img src="https://raw.githubusercontent.com/atagulalan/pipi-type/main/docs/banner-light.svg#gh-light-mode-only" width="50%" alt="pipi.type — Pi Zero W USB HID keyboard & mouse over Wi-Fi / Bluetooth"/>
<img src="https://raw.githubusercontent.com/atagulalan/pipi-type/main/docs/banner-dark.svg#gh-dark-mode-only" width="50%" alt="pipi.type — Pi Zero W USB HID keyboard & mouse over Wi-Fi / Bluetooth"/>


Control a **Raspberry Pi Zero W** that acts as a USB keyboard/mouse (HID gadget) for another device (Mac, iPad, PC). Your Linux PC talks to the Pi over **Wi‑Fi SSH** or **Bluetooth RFCOMM**; the Pi injects keystrokes and mouse moves into the USB host.

```
[PC: grab UI / web UI]
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
| `grab_app.py` | Grab logic + optional local HTTP UI (`pipi.grab`) |
| `serve.py` | Browser UI (`pipi.type`) — type box, grab pad, trackpad, Wi‑Fi/BT switch |
| `transport.py` | Shared SSH + Bluetooth transports (used by grab) |
| `bt_server.py` | **Runs on the Pi** — RFCOMM server (same line protocol as SSH `agent.py`) |
| `run.sh` | Launch `grab_gui.py` inside your graphical session |
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

## 2. Pi: USB HID gadget ([pi-hid](https://github.com/thiagofeijodev/pi-hid))

On the Pi:

```bash
sudo apt update
sudo apt install -y git python3-venv python3-pip bluez bluez-tools

git clone --depth 1 https://github.com/thiagofeijodev/pi-hid.git ~/pi-hid
cd ~/pi-hid
python3 -m venv hid-venv
./hid-venv/bin/pip install -U pip
./hid-venv/bin/pip install adafruit-circuitpython-hid
```

Enable the USB gadget overlays (paths may be `/boot/firmware/` on Bookworm):

```bash
# config.txt — peripheral mode
echo 'dtoverlay=dwc2,dr_mode=peripheral' | sudo tee -a /boot/firmware/config.txt

# cmdline.txt — load dwc2 early (append, do not replace the whole line)
sudo sed -i 's/$/ modules-load=dwc2/' /boot/firmware/cmdline.txt

# Avoid the host-mode driver fighting OTG
echo 'blacklist dwc_otg' | sudo tee /etc/modprobe.d/blacklist-dwc_otg.conf
```

Install / enable pi-hid’s HID setup scripts (see that repo’s README — typically `setup-hid.sh` + a systemd unit that creates `/dev/hidg0` keyboard and `/dev/hidg1` mouse). Reboot, plug the Pi’s **data** USB into the target device, then:

```bash
ls -l /dev/hidg*
```

You should see `hidg0` / `hidg1`.

### SSH agent (Wi‑Fi path)

pi-hid’s `~/pi-hid/webui/agent.py` speaks a simple line protocol over stdin. This project’s PC clients run:

```text
cd ~/pi-hid/webui && ../hid-venv/bin/python -u agent.py
```

via SSH (override with `PIPI_REMOTE` in `.env` if your paths differ).

Smoke test from the Pi while USB is plugged into a text field on the target:

```bash
cd ~/pi-hid/webui
../hid-venv/bin/python -c "from hid_type import HidTyper; HidTyper().type_text('hello from pipi')"
```

---

## 3. Pi: Bluetooth RFCOMM (optional)

Copy this repo’s `bt_server.py` onto the Pi next to the HID helpers, e.g.:

```bash
scp bt_server.py YOUR_USER@pipi.local:~/pi-hid/webui/
```

It imports `hid_type` from `~/pi-hid/webui` and listens on RFCOMM channel **1**.

Pair the Pi from your PC once (`bluetoothctl`), note the Pi’s MAC (`hcitool dev` / `bluetoothctl show`), then run on the Pi:

```bash
cd ~/pi-hid/webui
../hid-venv/bin/python -u bt_server.py
```

Optional systemd unit (`pi-hid-bt.service`) so it starts on boot — `WorkingDirectory` = `~/pi-hid/webui`, `ExecStart` = the venv python + `bt_server.py`.

Set `PIPI_BT` on the PC to that MAC.

---

## 4. PC: install this project

```bash
git clone <your-fork-or-repo-url> pipi-type
cd pipi-type
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
| `PIPI_UI_PORT` | no | `serve.py` port (default `8765`) |
| `PIPI_GRAB_PORT` | no | `grab_app.py` HTTP port (default `8765`) |
| `PIPI_REMOTE` | no | Remote command for SSH agent |

Never commit `.env`. Only `.env.example` goes to GitHub.

---

## 5. Run

Pi must be reachable (Wi‑Fi) and/or BT server running; USB HID plugged into the **target**.

### Native grab (recommended)

```bash
./run.sh
# or: python3 grab_gui.py
```

- Keyboard + mouse are grabbed exclusively and forwarded to the Pi.
- Release grab: press **Win / Super** four times quickly (configurable in code).

### Browser UIs

```bash
python3 serve.py          # http://127.0.0.1:8765  — type / grab / trackpad
python3 grab_app.py       # http://127.0.0.1:8765  — grab-focused page
```

Switch Wi‑Fi ↔ Bluetooth from the UI when both paths are set up.

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
| `sshpass` / auth fail | `.env` user/pass; try `ssh USER@HOST` manually |
| BT connect fails | Pair/trust Pi first; `bt_server.py` listening; correct `PIPI_BT` |
| Grab fails / no devices | User in `input` group; not grabbing virtual devices (keyd, ydotool, …) |
| Wayland browser grab weak | Prefer `grab_gui.py` / `evdev` over Pointer Lock in Firefox |

---

## Security notes

- Prefer **SSH keys** long-term; password + `sshpass` is convenient but stores `PIPI_PASS` in `.env`.
- BT server may run with relaxed RFCOMM link mode for simplicity — pair only devices you trust; don’t leave discoverable forever on untrusted networks.
- Bind UIs to `127.0.0.1` by default; don’t expose them on LAN without auth.

---

## License

Use / modify as you like for personal projects. Upstream HID stack: [thiagofeijodev/pi-hid](https://github.com/thiagofeijodev/pi-hid) (follow that project’s license).
