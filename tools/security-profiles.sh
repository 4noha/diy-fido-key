#!/bin/sh
# Build pico-fido with a selectable security profile.
#
#   backup     no secure boot, no flash encryption (default; everything reflashable)
#   encrypted  Secure Boot v2 (ECDSA P-256) + Flash Encryption in development mode
#   secure     Secure Boot v2 + Flash Encryption in release mode
#
# Only the *build* is produced here. Burning eFuses / enabling encryption on the
# device is a manual, irreversible step described in the generated
# FLASH-AND-BURN.md. Nothing in this script touches the hardware.
set -eu

MODE=${1:-}
ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
SRC="$ROOT/vendor/pico-fido"
KEYDIR=${XDG_CONFIG_HOME:-$HOME/.config}/diy-fido-key/secure-boot
KEY="$KEYDIR/secure-boot-ecdsa-p256.pem"

case "$MODE" in
    backup)
        exec sh "$ROOT/tools/build-pico-fido-esp32s3.sh"
        ;;
    encrypted|secure) ;;
    *)
        echo "usage: sh tools/security-profiles.sh [backup|encrypted|secure]" >&2
        exit 2
        ;;
esac

if ! command -v idf.py >/dev/null 2>&1 || ! command -v espsecure.py >/dev/null 2>&1; then
    echo "ESP-IDF v5.5.1 is not exported ('. ~/esp/esp-idf-v5.5.1/export.sh')." >&2
    exit 1
fi
if [ ! -d "$SRC/pico-keys-sdk" ]; then
    echo "vendor/pico-fido is missing." >&2
    exit 1
fi

umask 077
mkdir -p "$KEYDIR"
chmod 700 "$KEYDIR"
if [ ! -f "$KEY" ]; then
    echo "Generating ECDSA P-256 signing key: $KEY"
    espsecure.py generate_signing_key --version 2 --scheme ecdsa256 "$KEY"
fi
chmod 600 "$KEY"

BUILD="$ROOT/build/pico-fido-$MODE"
SDKCONFIG="$SRC/sdkconfig"

sh "$ROOT/tools/install-esp32-lcd.sh" >/dev/null

# Keep the normal sdkconfig intact; the security settings live only for this run.
if [ -f "$SDKCONFIG" ]; then
    cp "$SDKCONFIG" "$SDKCONFIG.pre-security"
    trap 'mv -f "$SDKCONFIG.pre-security" "$SDKCONFIG"' EXIT INT TERM
fi


idf.py -B "$BUILD" -C "$SRC" set-target esp32s3
# set-target regenerates sdkconfig from defaults, so apply the security
# settings afterwards and build straight away.
python3 - "$SDKCONFIG" "$MODE" "$KEY" <<'PY2'
import os, sys
path, mode, key = sys.argv[1], sys.argv[2], sys.argv[3]
text = open(path).read() if os.path.exists(path) else ''

def set_sym(text, name, value=None):
    lines = [l for l in text.splitlines() if not l.startswith(name + '=')]
    if value is None:
        lines.append('# %s is not set' % name)
    else:
        lines.append('%s=%s' % (name, value))
    return '\n'.join(lines) + '\n'

text = set_sym(text, 'CONFIG_SECURE_BOOT', 'y')
text = set_sym(text, 'CONFIG_SECURE_BOOT_V2_ENABLED', 'y')
text = set_sym(text, 'CONFIG_SECURE_BOOT_BUILD_SIGNED_BINARIES', 'y')
text = set_sym(text, 'CONFIG_SECURE_BOOT_SIGNING_KEY', '"%s"' % key)
text = set_sym(text, 'CONFIG_SECURE_FLASH_ENC_ENABLED', 'y')
# The signed bootloader exceeds 32 KB, so move the partition table up.
text = set_sym(text, 'CONFIG_PARTITION_TABLE_OFFSET', '0x10000')
if mode == 'encrypted':
    text = set_sym(text, 'CONFIG_SECURE_FLASH_ENCRYPTION_MODE_DEVELOPMENT', 'y')
    text = set_sym(text, 'CONFIG_SECURE_FLASH_ENCRYPTION_MODE_RELEASE', None)
else:
    text = set_sym(text, 'CONFIG_SECURE_FLASH_ENCRYPTION_MODE_RELEASE', 'y')
    text = set_sym(text, 'CONFIG_SECURE_FLASH_ENCRYPTION_MODE_DEVELOPMENT', None)
open(path, 'w').write(text)
PY2
idf.py -B "$BUILD" -C "$SRC" build

esptool --chip esp32s3 merge-bin \
    -o "$BUILD/pico_fido_$MODE.bin" \
    --flash-mode dio --flash-freq 80m --flash-size 4MB \
    0x0 "$BUILD/bootloader/bootloader.bin" \
    0x10000 "$BUILD/partition_table/partition-table.bin" \
    0x20000 "$BUILD/pico_fido.bin"

if [ "$MODE" = encrypted ]; then
    ENC_NOTE='Flash with --encrypt (development mode lets the ROM encrypt on write).'
    MODE_NOTE='Development mode: the flash key stays readable via download mode, so this protects casual dumps only.'
else
    ENC_NOTE='First boot generates the flash key and encrypts the image. Later updates must use --encrypt with the same key.'
    MODE_NOTE='Release mode: the ROM download mode can no longer use the encryption hardware. Keep the flash key.'
fi

cat > "$BUILD/FLASH-AND-BURN.md" <<EOF
# $MODE build: flash and eFuse steps

Build artifact: \`pico_fido_$MODE.bin\` (Secure Boot v2 signed, ECDSA P-256)

## Before anything else

- Back up the signing key \`$KEY\` to two offline places.
- Back up the current device flash (encrypted .aesgcm) if you still need it.
- Once the eFuses below are burned the device can only run signed images, and
  only be reflashed with this key.

## 1. Flash the signed image

    esptool --chip esp32s3 --port /dev/cu.usbmodemXXXX write-flash 0x0 build/pico-fido-$MODE/pico_fido_$MODE.bin

$ENC_NOTE

## 2. Burn the Secure Boot digest (irreversible)

    espefuse.py --port /dev/cu.usbmodemXXXX burn_key_digest "$KEY"
    espefuse.py --port /dev/cu.usbmodemXXXX burn_efuse SECURE_BOOT_EN

Order matters: burn the digest first, then enable secure boot.

## 3. Flash encryption

$MODE_NOTE

## 4. pico-fido Secure Lock (optional, irreversible)

Enable it from PicoKey App (Security) after secure boot is active. This moves
the credential master key into OTP and ties resident keys to this device.

## Recovery rules

- Losing \`$KEY\` means no further firmware updates.
- Do not disable download mode until the signed image is confirmed working.
- Never flash an unsigned image after step 2: the ROM will refuse to boot it.
EOF

echo "Built: $BUILD/pico_fido_$MODE.bin"
echo "Procedure: $BUILD/FLASH-AND-BURN.md"
echo "Signing key: $KEY (back this up offline)"
