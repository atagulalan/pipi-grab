#!/bin/bash
# PC-side: if Wi-Fi SSH works and the Pi lacks our HID stack, install it over SSH.
# Safe to run often — exits quickly when already OK.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

set -a
[ -f .env ] && . ./.env
set +a

HOST="${PIPI_HOST:-}"
USER_N="${PIPI_USER:-}"
PASS="${PIPI_PASS:-}"
SKIP="${PIPI_SKIP_ENSURE:-0}"

if [ "$SKIP" = "1" ] || [ "$SKIP" = "true" ]; then
  echo "ensure_pi: skipped (PIPI_SKIP_ENSURE=1)"
  exit 0
fi

if [ -z "$HOST" ] || [ -z "$USER_N" ] || [ -z "$PASS" ]; then
  echo "ensure_pi: no PIPI_HOST/USER/PASS — skip"
  exit 0
fi

if ! command -v sshpass >/dev/null; then
  echo "ensure_pi: sshpass missing — install sshpass" >&2
  exit 1
fi

ssh_base=(
  sshpass -p "$PASS" ssh
  -o StrictHostKeyChecking=no
  -o UserKnownHostsFile=/dev/null
  -o PreferredAuthentications=password
  -o PubkeyAuthentication=no
  -o ConnectTimeout=8
  -o ServerAliveInterval=3
  "$USER_N@$HOST"
)
scp_base=(
  sshpass -p "$PASS" scp
  -o StrictHostKeyChecking=no
  -o UserKnownHostsFile=/dev/null
  -o PreferredAuthentications=password
  -o PubkeyAuthentication=no
  -o ConnectTimeout=8
)

want_ver="$(tr -d '[:space:]' < "$ROOT/pi/VERSION")"

remote() {
  "${ssh_base[@]}" "$@"
}

check_remote() {
  remote "VER_WANT='$want_ver' bash -s" <<'REMOTE'
set +e
MARKER=$(cat /etc/pipi-grab.ver 2>/dev/null | tr -d '[:space:]')
LEN=$(cat /sys/kernel/config/usb_gadget/pi_hid/functions/hid.usb1/report_length 2>/dev/null | tr -d '[:space:]')
SUB=$(cat /sys/kernel/config/usb_gadget/pi_hid/functions/hid.usb1/subclass 2>/dev/null | tr -d '[:space:]')
HID0=$(test -c /dev/hidg0 && echo 1 || echo 0)
HID1=$(test -c /dev/hidg1 && echo 1 || echo 0)
AGENT=$(test -f "$HOME/pi-hid/webui/agent.py" && echo 1 || echo 0)
HT=$(test -f "$HOME/pi-hid/webui/hid_type.py" && echo 1 || echo 0)
# ver3+: classic 4-byte mouse, subclass 0
if [ "$MARKER" = "$VER_WANT" ] && [ "$LEN" = "4" ] && [ "$SUB" = "0" ] \
  && [ "$HID0" = "1" ] && [ "$HID1" = "1" ] && [ "$AGENT" = "1" ] && [ "$HT" = "1" ]; then
  echo OK
else
  echo "NEED marker=$MARKER len=$LEN sub=$SUB hid=$HID0/$HID1 agent=$AGENT"
fi
REMOTE
}

echo "ensure_pi: checking $USER_N@$HOST (want ver=$want_ver)…"
if ! status="$(check_remote 2>/dev/null)"; then
  echo "ensure_pi: SSH unreachable — skip install" >&2
  exit 0
fi

if [ "$status" = "OK" ]; then
  echo "ensure_pi: already installed (ver=$want_ver)"
  exit 0
fi

echo "ensure_pi: $status — installing over SSH…"
STAGE="/tmp/pipi-grab-pi-$$"
remote "mkdir -p '$STAGE' && printf '%s\n' '$USER_N' > '$STAGE/.install_user'"
"${scp_base[@]}" \
  "$ROOT/pi/setup-hid.sh" \
  "$ROOT/pi/hid_type.py" \
  "$ROOT/pi/agent.py" \
  "$ROOT/pi/bt_server.py" \
  "$ROOT/pi/10-hidg.rules" \
  "$ROOT/pi/hid-gadget.service" \
  "$ROOT/pi/pi-hid-bt.service" \
  "$ROOT/pi/VERSION" \
  "$ROOT/pi/install_remote.sh" \
  "$USER_N@$HOST:$STAGE/"

remote "chmod +x '$STAGE/install_remote.sh' && printf '%s\n' '$PASS' | sudo -S -p '' env PIPI_INSTALL_USER='$USER_N' bash '$STAGE/install_remote.sh'"

status2="$(check_remote 2>/dev/null || echo FAIL)"
if [ "$status2" = "OK" ]; then
  echo "ensure_pi: install OK"
  exit 0
fi
echo "ensure_pi: after install → $status2" >&2
echo "ensure_pi: if overlays were first-time, reboot the Pi and re-run ./ensure_pi.sh" >&2
exit 1
