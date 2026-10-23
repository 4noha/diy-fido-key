#!/bin/sh
# Install the ST7735 status display into the pico-fido ESP32 checkout.
# vendor/ is not tracked, so this keeps the patch reproducible after re-cloning.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
SRC="$ROOT/esp32-lcd"
SDK="$ROOT/vendor/pico-fido/pico-keys-sdk"
DEST="$SDK/src/lcd"

if [ ! -d "$SDK" ]; then
    echo "vendor/pico-fido/pico-keys-sdk is missing; clone pico-fido first." >&2
    exit 1
fi

mkdir -p "$DEST"
cp "$SRC/fido_status_lcd.c" "$SRC/fido_status_lcd.h" "$SRC/font5x7.h" "$DEST/"
if [ -f "$SRC/mascot_80x80.h" ]; then
    cp "$SRC/mascot_80x80.h" "$DEST/"
    echo "mascot_80x80.h installed"
else
    rm -f "$DEST/mascot_80x80.h"
    echo "no mascot_80x80.h; display will use the text placeholder"
fi

IMPORT="$SDK/picokeys_sdk_import.cmake"
if ! grep -q 'src/lcd/fido_status_lcd.c' "$IMPORT"; then
    perl -0pi -e 's{(\$\{CMAKE_CURRENT_LIST_DIR\}/src/led/led\.c\n)}{$1    \$\{CMAKE_CURRENT_LIST_DIR\}/src/lcd/fido_status_lcd.c\n}' "$IMPORT"
fi

COMP="$SDK/config/esp32/components/pico-keys-sdk/CMakeLists.txt"
if ! grep -q 'src/lcd' "$COMP"; then
    perl -0pi -e 's{(\$\{PICOKEYS_SDK_DIR\}/src/led\n)}{$1    \$\{PICOKEYS_SDK_DIR\}/src/lcd\n}' "$COMP"
fi
if ! grep -q 'esp_driver_spi' "$COMP"; then
    perl -0pi -e 's{(\n\s*mbedtls\n\))}{\n    mbedtls\n    esp_driver_spi\n    esp_psram\n)}' "$COMP"
fi
if ! grep -q 'FIDO_STATUS_LCD' "$COMP"; then
    perl -0pi -e 's{(idf_component_set_property\(\$\{COMPONENT_NAME\} WHOLE_ARCHIVE ON\))}{target_compile_definitions(\$\{COMPONENT_LIB\} PUBLIC FIDO_STATUS_LCD=1)\n\noption(LCD_CALIBRATION "Build the panel calibration UI" OFF)\nif(LCD_CALIBRATION)\n    target_compile_definitions(\$\{COMPONENT_LIB\} PUBLIC LCD_CALIBRATION=1)\nendif()\n\n$1}' "$COMP"
fi

TOP="$ROOT/vendor/pico-fido/CMakeLists.txt"
if ! grep -q 'NOT DEFINED USB_VID' "$TOP"; then
    perl -0pi -e 's{set\(USB_VID 0x2E8A\)\nset\(USB_PID 0x10FE\)}{if(NOT DEFINED USB_VID)\n    set(USB_VID 0x2E8A)\nendif()\nif(NOT DEFINED USB_PID)\n    set(USB_PID 0x10FE)\nendif()}' "$TOP"
fi


# --- ESP32 flash-encryption workaround: keep part0 in a PSRAM shadow ---
# pico-fido mmaps part0, but flash encryption decrypts every mapping, so the
# credential filesystem cannot round-trip. Replace the mapping with a RAM
# shadow fed by plaintext esp_flash_read/write calls.
SHADOW_PATCH="$ROOT/patches/pico-fido-psram-shadow.patch"
if [ -f "$SHADOW_PATCH" ] && ! grep -q 'fido_flash_shadow' "$SDK/src/fs/low_flash.c"; then
    (cd "$SDK" && patch -p1 < "$SHADOW_PATCH")
fi

MAIN="$SDK/src/main.c"
if ! grep -q 'fido_status_lcd.h' "$MAIN"; then
    perl -0pi -e 's{(#include "led/led\.h"\n)}{$1#ifdef FIDO_STATUS_LCD\n#include "fido_status_lcd.h"\n#endif\n}' "$MAIN"
fi
if ! grep -q 'fido_status_lcd_init' "$MAIN"; then
    # Start the display only after USB is installed, so a panel fault cannot
    # keep the FIDO interface from enumerating.
    perl -0pi -e 's{(xTaskCreatePinnedToCore\(core0_loop[^\n]*\n)}{$1#ifdef FIDO_STATUS_LCD\n    fido_status_lcd_init();\n#endif\n}' "$MAIN"
fi

echo "LCD status display installed into pico-fido."
