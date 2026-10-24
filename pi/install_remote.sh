#!/bin/bash
# Runs ON the Pi. Installs / refreshes pipi.grab HID stack (Mac-friendly mouse).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
VER="$(tr -d '[:space:]' < "$HERE/VERSION")"
MARKER=/etc/pipi-grab.ver

if [ -f "$HERE/.install_user" ]; then
  PI_USER="$(tr -d '[:space:]' < "$HERE/.install_user")"
elif [ -n "${PIPI_INSTALL_USER:-}" ]; then
  PI_USER="$PIPI_INSTALL_USER"
elif [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != root ]; then
  PI_USER="$SUDO_USER"
else
  PI_USER="${USER:-pi}"
fi
PI_HOME="$(getent passwd "$PI_USER" | cut -d: -f6)"
if [ -z "$PI_HOME" ]; then
  echo "cannot resolve home for $PI_USER" >&2
  exit 1
fi

echo "pipi.grab Pi install → user=$PI_USER home=$PI_HOME ver=$VER"

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq git python3-venv python3-pip bluez bluez-tools

CFG=/boot/firmware/config.txt
[ -f "$CFG" ] || CFG=/boot/config.txt
CMDLINE=/boot/firmware/cmdline.txt
[ -f "$CMDLINE" ] || CMDLINE=/boot/cmdline.txt

if [ -f "$CFG" ] && ! grep -q 'dtoverlay=dwc2' "$CFG"; then
  echo 'dtoverlay=dwc2,dr_mode=peripheral' >> "$CFG"
  echo "added dwc2 overlay to $CFG"
fi
if [ -f "$CMDLINE" ] && ! grep -q 'modules-load=dwc2' "$CMDLINE"; then
  sed -i 's/$/ modules-load=dwc2/' "$CMDLINE"
  echo "added modules-load=dwc2 to $CMDLINE"
fi
echo 'blacklist dwc_otg' > /etc/modprobe.d/blacklist-dwc_otg.conf

if [ ! -d "$PI_HOME/pi-hid/.git" ]; then
  sudo -u "$PI_USER" git clone --depth 1 https://github.com/thiagofeijodev/pi-hid.git "$PI_HOME/pi-hid"
fi
sudo -u "$PI_USER" bash -c "
  cd '$PI_HOME/pi-hid'
  python3 -m venv hid-venv
  ./hid-venv/bin/pip -q install -U pip
  ./hid-venv/bin/pip -q install adafruit-circuitpython-hid
"

install -d -o "$PI_USER" -g "$PI_USER" "$PI_HOME/pi-hid/driver" "$PI_HOME/pi-hid/webui"
install -m 755 -o "$PI_USER" -g "$PI_USER" "$HERE/setup-hid.sh" "$PI_HOME/pi-hid/driver/setup-hid.sh"
install -m 644 -o "$PI_USER" -g "$PI_USER" "$HERE/hid_type.py" "$PI_HOME/pi-hid/webui/hid_type.py"
install -m 755 -o "$PI_USER" -g "$PI_USER" "$HERE/agent.py" "$PI_HOME/pi-hid/webui/agent.py"
install -m 755 -o "$PI_USER" -g "$PI_USER" "$HERE/bt_server.py" "$PI_HOME/pi-hid/webui/bt_server.py"

install -m 644 "$HERE/10-hidg.rules" /etc/udev/rules.d/10-hidg.rules
udevadm control --reload-rules || true

install -m 755 "$HERE/setup-hid.sh" /usr/bin/setup-hid.sh
install -m 644 "$HERE/hid-gadget.service" /etc/systemd/system/hid-gadget.service
sed "s|__PI_HOME__|$PI_HOME|g" "$HERE/pi-hid-bt.service" > /etc/systemd/system/pi-hid-bt.service

systemctl daemon-reload
systemctl enable hid-gadget.service pi-hid-bt.service

modprobe libcomposite 2>/dev/null || true
modprobe dwc2 2>/dev/null || true

apply_gadget() {
  local UDC
  UDC="$(ls /sys/class/udc 2>/dev/null | head -1 || true)"
  [ -n "$UDC" ] || return 1

  systemctl stop pi-hid-bt.service 2>/dev/null || true
  fuser -k /dev/hidg0 /dev/hidg1 2>/dev/null || true
  sleep 0.3
  # setup-hid.sh is idempotent (tears down pi_hid then recreates)
  /usr/bin/setup-hid.sh
  chmod 666 /dev/hidg0 /dev/hidg1 2>/dev/null || true
}

if apply_gadget; then
  echo "gadget applied"
else
  # Fresh machine: run setup-hid once (creates gadget). Do NOT restart
  # hid-gadget.service afterward — that re-runs setup-hid and hits EBUSY.
  if [ ! -d /sys/kernel/config/usb_gadget/pi_hid ]; then
    /usr/bin/setup-hid.sh || true
  fi
  echo "WARN: if hidg missing, reboot after first overlay install"
fi

systemctl reset-failed hid-gadget.service 2>/dev/null || true
systemctl restart pi-hid-bt.service 2>/dev/null || true
chmod 666 /dev/hidg0 /dev/hidg1 2>/dev/null || true

echo "$VER" > "$MARKER"
echo "OK pipi.grab Pi install complete (ver=$VER)"
ls -l /dev/hidg0 /dev/hidg1 2>/dev/null || echo "(hidg missing until reboot/UDC)"
