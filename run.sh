#!/bin/bash
cd "$(dirname "$0")"
# Load local secrets for the session unit
set -a
[ -f .env ] && . ./.env
set +a
# Run inside the graphical user session (Wayland/DBus)
exec systemd-run --user --same-dir --collect \
  -E DISPLAY="${DISPLAY:-:0}" \
  -E WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-0}" \
  -E PIPI_HOST -E PIPI_USER -E PIPI_PASS -E PIPI_BT -E PIPI_BT_CH \
  -E PIPI_MODE -E PIPI_REMOTE \
  /usr/bin/python3 -u "$(pwd)/grab_gui.py"
