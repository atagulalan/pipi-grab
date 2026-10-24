#!/bin/bash -e
# pipi.grab HID gadget — keyboard + relative mouse
# Mouse: classic 4-byte boot-style report (buttons, X, Y, wheel) with subclass=0
# so macOS accepts move/click/wheel. (Avoid dual-open / exotic 5-byte stalls.)

modprobe libcomposite
modprobe dwc2 2>/dev/null || true

cd /sys/kernel/config/usb_gadget || exit 1

if [ -d pi_hid ]; then
  echo "" > pi_hid/UDC 2>/dev/null || true
  sleep 0.3
  rm -f pi_hid/configs/c.1/hid.usb0 pi_hid/configs/c.1/hid.usb1 2>/dev/null || true
  rmdir pi_hid/configs/c.1/strings/0x409 2>/dev/null || true
  rmdir pi_hid/configs/c.1 2>/dev/null || true
  rmdir pi_hid/functions/hid.usb0 2>/dev/null || true
  rmdir pi_hid/functions/hid.usb1 2>/dev/null || true
  rmdir pi_hid/strings/0x409 2>/dev/null || true
  rmdir pi_hid 2>/dev/null || true
fi

mkdir -p pi_hid
cd pi_hid

echo 0x1d6b > idVendor
echo 0x0104 > idProduct
echo 0x0100 > bcdDevice
echo 0x0200 > bcdUSB

mkdir -p strings/0x409
echo "tfr669717667269" > strings/0x409/serialnumber
echo "Keycron" > strings/0x409/manufacturer
echo "Net USB Device" > strings/0x409/product

mkdir -p configs/c.1/strings/0x409
echo "Config 1: Keyboard + Mouse" > configs/c.1/strings/0x409/configuration
echo 250 > configs/c.1/MaxPower

# Keyboard
mkdir -p functions/hid.usb0
echo 1 > functions/hid.usb0/protocol
echo 1 > functions/hid.usb0/subclass
echo 8 > functions/hid.usb0/report_length
echo -ne \
'\x05\x01\x09\x06\xa1\x01\x05\x07\x19\xe0\x29\xe7\x15\x00\x25\x01\x75\x01\x95\x08\x81\x02\x95\x01\x75\x08\x81\x03\x95\x05\x75\x01\x05\x08\x19\x01\x29\x05\x91\x02\x95\x01\x75\x03\x91\x03\x95\x06\x75\x08\x15\x00\x25\x65\x05\x07\x19\x00\x29\x65\x81\x00\xc0' \
> functions/hid.usb0/report_desc

# Mouse — 4-byte: buttons(1) + X + Y + Wheel; subclass 0 (report proto) for Mac wheel
mkdir -p functions/hid.usb1
echo 2 > functions/hid.usb1/protocol
echo 0 > functions/hid.usb1/subclass
echo 4 > functions/hid.usb1/report_length
echo -ne \
'\x05\x01\x09\x02\xa1\x01\x09\x01\xa1\x00\x05\x09\x19\x01\x29\x03\x15\x00\x25\x01\x95\x03\x75\x01\x81\x02\x95\x01\x75\x05\x81\x03\x05\x01\x09\x30\x09\x31\x09\x38\x15\x81\x25\x7f\x75\x08\x95\x03\x81\x06\xc0\xc0' \
> functions/hid.usb1/report_desc

ln -s functions/hid.usb0 configs/c.1/ 2>/dev/null || true
ln -s functions/hid.usb1 configs/c.1/ 2>/dev/null || true

ls /sys/class/udc > UDC
sleep 0.5
chmod 666 /dev/hidg0 /dev/hidg1 2>/dev/null || true
