#!/bin/sh
# Build pico-fido with a selectable security profile.
#
#   backup             no secure boot, no flash encryption (default, reflashable)
#   encrypted          Secure Boot v2 (ECDSA P-256) + Flash Encryption dev mode
#   encrypted-release  Flash Encryption release mode only (no secure boot)
#   secure             Secure Boot v2 + Flash Encryption release mode
#
# This script only produces images and the procedure text. It never writes
# eFuses and never flashes the device.
set -eu

MODE=${1:-}
ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
SRC="$ROOT/vendor/pico-fido"
KEYDIR=${XDG_CONFIG_HOME:-$HOME/.config}/diy-fido-key/secure-boot
SB_KEY="$KEYDIR/secure-boot-rsa3072.pem"
FE_KEY="$KEYDIR/flash-encryption-key.bin"

case "$MODE" in
    backup)
        exec sh "$ROOT/tools/build-pico-fido-esp32s3.sh"
        ;;
    encrypted|encrypted-release|secure) ;;
    *)
        echo "usage: sh tools/security-profiles.sh [backup|encrypted|encrypted-release|secure]" >&2
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

if [ "$MODE" != encrypted-release ] && [ ! -f "$SB_KEY" ]; then
    echo "Generating ECDSA P-256 signing key: $SB_KEY"
    espsecure.py generate_signing_key --version 2 --scheme rsa3072 "$SB_KEY"
fi
[ -f "$SB_KEY" ] && chmod 600 "$SB_KEY"

if { [ "$MODE" = encrypted-release ] || [ "$MODE" = secure ]; } && [ ! -f "$FE_KEY" ]; then
    echo "Generating flash encryption key: $FE_KEY"
    espsecure.py generate_flash_encryption_key "$FE_KEY"
    chmod 600 "$FE_KEY"
fi

BUILD="$ROOT/build/pico-fido-$MODE"
SDKCONFIG="$SRC/sdkconfig"

sh "$ROOT/tools/install-esp32-lcd.sh" >/dev/null

if [ -f "$SDKCONFIG" ]; then
    cp "$SDKCONFIG" "$SDKCONFIG.pre-security"
    trap 'mv -f "$SDKCONFIG.pre-security" "$SDKCONFIG"' EXIT INT TERM
fi

idf.py -B "$BUILD" -C "$SRC" set-target esp32s3

# set-target regenerates sdkconfig from defaults, so apply the security
# settings afterwards and build straight away.
python3 - "$SDKCONFIG" "$MODE" "$SB_KEY" <<'PY'
import os, sys
path, mode, sb_key = sys.argv[1], sys.argv[2], sys.argv[3]
text = open(path).read() if os.path.exists(path) else ''

def set_sym(text, name, value=None):
    lines = [l for l in text.splitlines() if not l.startswith(name + '=')]
    if value is None:
        lines.append('# %s is not set' % name)
    else:
        lines.append('%s=%s' % (name, value))
    return '\n'.join(lines) + '\n'

if mode == 'encrypted-release':
    text = set_sym(text, 'CONFIG_SECURE_BOOT', None)
else:
    text = set_sym(text, 'CONFIG_SECURE_BOOT', 'y')
    text = set_sym(text, 'CONFIG_SECURE_BOOT_V2_ENABLED', 'y')
    text = set_sym(text, 'CONFIG_SECURE_BOOT_BUILD_SIGNED_BINARIES', 'y')
    text = set_sym(text, 'CONFIG_SECURE_BOOT_SIGNING_KEY', '"%s"' % sb_key)
    # ESP32-S3 only supports RSA-3072 for Secure Boot v2.
    text = set_sym(text, 'CONFIG_SECURE_SIGNED_APPS_RSA_SCHEME', 'y')

text = set_sym(text, 'CONFIG_SECURE_FLASH_ENC_ENABLED', 'y')
text = set_sym(text, 'CONFIG_SPIRAM', 'y')
text = set_sym(text, 'CONFIG_SPIRAM_MODE_OCT', 'y')
text = set_sym(text, 'CONFIG_SPIRAM_SPEED_40M', 'y')
text = set_sym(text, 'CONFIG_SPIRAM_USE_MALLOC', 'y')
text = set_sym(text, 'CONFIG_SPIRAM_BOOT_INIT', 'y')
text = set_sym(text, 'CONFIG_SPIRAM_IGNORE_NOTFOUND', 'y')

if mode == 'encrypted':
    text = set_sym(text, 'CONFIG_SECURE_FLASH_ENCRYPTION_MODE_DEVELOPMENT', 'y')
    text = set_sym(text, 'CONFIG_SECURE_FLASH_ENCRYPTION_MODE_RELEASE', None)
else:
    text = set_sym(text, 'CONFIG_SECURE_FLASH_ENCRYPTION_MODE_RELEASE', 'y')
    text = set_sym(text, 'CONFIG_SECURE_FLASH_ENCRYPTION_MODE_DEVELOPMENT', None)

if mode == 'encrypted-release':
    # Flash encryption pushes the bootloader past 32 KB.
    text = set_sym(text, 'CONFIG_PARTITION_TABLE_OFFSET', '0x9000')
else:
    # The signed bootloader exceeds 32 KB, so move the partition table up.
    text = set_sym(text, 'CONFIG_PARTITION_TABLE_OFFSET', '0x10000')

open(path, 'w').write(text)
PY

idf.py -B "$BUILD" -C "$SRC" build

PT_OFFSET=0x10000
[ "$MODE" = encrypted-release ] && PT_OFFSET=0x9000

esptool --chip esp32s3 merge-bin \
    -o "$BUILD/pico_fido_$MODE.bin" \
    --flash-mode dio --flash-freq 80m --flash-size 4MB \
    0x0 "$BUILD/bootloader/bootloader.bin" \
    $PT_OFFSET "$BUILD/partition_table/partition-table.bin" \
    0x20000 "$BUILD/pico_fido.bin"

IMAGE="$BUILD/pico_fido_$MODE.bin"

# Release-mode encryption cannot be done by the ROM, so pre-encrypt on the host.
if [ "$MODE" = encrypted-release ] || [ "$MODE" = secure ]; then
    espsecure.py encrypt_flash_data --aes_xts --keyfile "$FE_KEY" --address 0x0 \
        --output "$BUILD/pico_fido_$MODE.enc.bin" "$IMAGE"
    IMAGE="$BUILD/pico_fido_$MODE.enc.bin"
fi

case "$MODE" in
    encrypted)
        STEPS="1. Flash the signed image (plaintext; the ROM encrypts on first boot):
   esptool --chip esp32s3 --port /dev/cu.usbmodemXXXX write-flash --encrypt 0x0 $IMAGE
2. Optional secure boot (irreversible):
   espefuse.py --port /dev/cu.usbmodemXXXX burn_key_digest $SB_KEY
   espefuse.py --port /dev/cu.usbmodemXXXX burn_efuse SECURE_BOOT_EN
3. pico-fido Secure Lock (only after secure boot): PicoKey App > Security."
        NOTE="Development mode lets the ROM encrypt on write. Anyone with USB access can also flash their own plaintext, so this protects against flash dumps, not against tampering."
        ;;
    encrypted-release)
        STEPS="1. Burn the flash encryption key (irreversible):
   espefuse.py --port /dev/cu.usbmodemXXXX burn_key BLOCK_KEY0 $FE_KEY XTS_AES_128_KEY
2. Write the pre-encrypted image:
   esptool --chip esp32s3 --port /dev/cu.usbmodemXXXX write-flash 0x0 $IMAGE
3. Reboot. No secure boot eFuses are used."
        NOTE="Release mode blocks the ROM from encrypting writes, so arbitrary firmware cannot be flashed and flash dumps stay ciphertext. Boot integrity is NOT verified (no secure boot)."
        ;;
    secure)
        STEPS="1. Burn the flash encryption key (irreversible):
   espefuse.py --port /dev/cu.usbmodemXXXX burn_key BLOCK_KEY0 $FE_KEY XTS_AES_128_KEY
2. Write the pre-encrypted, signed image:
   esptool --chip esp32s3 --port /dev/cu.usbmodemXXXX write-flash 0x0 $IMAGE
3. Burn the secure boot digest, then enable it (irreversible):
   espefuse.py --port /dev/cu.usbmodemXXXX burn_key_digest $SB_KEY
   espefuse.py --port /dev/cu.usbmodemXXXX burn_efuse SECURE_BOOT_EN
4. pico-fido Secure Lock (optional): PicoKey App > Security."
        NOTE="Full protection: encrypted flash, no unsigned boot, ROM cannot encrypt writes. Keep both keys offline."
        ;;
esac

cat > "$BUILD/FLASH-AND-BURN.md" <<EOF
# $MODE build

Image: \`$IMAGE\`

$STEPS

## Notes

$NOTE

- Signing key: $SB_KEY
- Flash encryption key: $( [ -f "$FE_KEY" ] && echo "$FE_KEY" || echo "(device generated on first boot)" )
- Losing the keys means no further updates. Keep offline copies.
- Do not disable download mode until the image is confirmed working.
EOF

echo "Built: $IMAGE"
echo "Procedure: $BUILD/FLASH-AND-BURN.md"
