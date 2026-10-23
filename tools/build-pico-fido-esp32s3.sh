#!/bin/sh
# Build pico-fido for the ESP32-S3 board (ST7735 80x160) and emit a merged image.
# Requires ESP-IDF v5.5.1 exported in the environment (idf.py on PATH).
set -e

ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
SRC="$ROOT/vendor/pico-fido"
BUILD="$ROOT/build/pico-fido-esp32s3"

if [ ! -d "$SRC/pico-keys-sdk" ]; then
    echo "vendor/pico-fido is missing; clone it first (see README)." >&2
    exit 1
fi
if ! command -v idf.py >/dev/null 2>&1; then
    echo "idf.py not found; run '. ~/esp/esp-idf-v5.5.1/export.sh' first." >&2
    exit 1
fi

# Reproducible local patches: LCD status UI.
sh "$ROOT/tools/install-esp32-lcd.sh"

# On ESP32-S3 the USB Serial/JTAG console shares GPIO19/20 with USB-OTG.
# Leaving the secondary console enabled makes the firmware watchdog-loop
# before TinyUSB can enumerate the FIDO HID interface. DIO matches the
# upstream build and is the only mode verified on this board.
if [ -f "$SRC/sdkconfig" ]; then
    python3 - "$SRC/sdkconfig" <<'PY'
import sys
path = sys.argv[1]
text = open(path).read()
replacements = {
    '# CONFIG_ESP_CONSOLE_SECONDARY_NONE is not set': 'CONFIG_ESP_CONSOLE_SECONDARY_NONE=y',
    'CONFIG_ESP_CONSOLE_SECONDARY_USB_SERIAL_JTAG=y': '# CONFIG_ESP_CONSOLE_SECONDARY_USB_SERIAL_JTAG is not set',
    'CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG_ENABLED=y': '# CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG_ENABLED is not set',
    'CONFIG_ESPTOOLPY_FLASHMODE_QIO=y': '# CONFIG_ESPTOOLPY_FLASHMODE_QIO is not set',
    '# CONFIG_ESPTOOLPY_FLASHMODE_DIO is not set': 'CONFIG_ESPTOOLPY_FLASHMODE_DIO=y',
    'CONFIG_ESPTOOLPY_FLASHMODE="qio"': 'CONFIG_ESPTOOLPY_FLASHMODE="dio"',
}
spiram = {
    'CONFIG_SPIRAM': 'y',
    'CONFIG_SPIRAM_MODE_OCT': 'y',
    'CONFIG_SPIRAM_SPEED_80M': 'y',
    'CONFIG_SPIRAM_USE_MALLOC': 'y',
    'CONFIG_SPIRAM_BOOT_INIT': 'y',
    'CONFIG_SPIRAM_IGNORE_NOTFOUND': 'y',
}
for old, new in replacements.items():
    text = text.replace(old, new)
for name, value in spiram.items():
    lines = [l for l in text.splitlines() if not l.startswith(name + '=')]
    lines.append('%s=%s' % (name, value))
    text = '\n'.join(lines) + '\n'
open(path, 'w').write(text)
PY
fi

: "${FIDO_USB_VID:=0x2E8A}"
: "${FIDO_USB_PID:=0x10FE}"

idf.py -B "$BUILD" -C "$SRC" -DUSB_VID="$FIDO_USB_VID" -DUSB_PID="$FIDO_USB_PID" set-target esp32s3
idf.py -B "$BUILD" -C "$SRC" -DUSB_VID="$FIDO_USB_VID" -DUSB_PID="$FIDO_USB_PID" build

esptool --chip esp32s3 merge-bin \
    -o "$BUILD/pico_fido_full.bin" \
    --flash-mode dio --flash-freq 80m --flash-size 4MB \
    0x0 "$BUILD/bootloader/bootloader.bin" \
    0x8000 "$BUILD/partition_table/partition-table.bin" \
    0x20000 "$BUILD/pico_fido.bin"

echo "Merged image: $BUILD/pico_fido_full.bin"
echo "Flash: hold BOOT (GPIO0) while plugging in, then:"
echo "  esptool --chip esp32s3 --port /dev/cu.usbmodemXXXX write-flash 0x0 $BUILD/pico_fido_full.bin"
echo "After flashing, release BOOT and replug."
