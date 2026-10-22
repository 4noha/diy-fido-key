"""Import a PEM P-256 key over USB; BOOT approval is required on the device."""
import argparse
import base64
import uuid
import getpass
import json
import os
import re
import time
from pathlib import Path
import cbor2
import serial
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def load_key(path):
    data = path.read_bytes()
    try:
        key = serialization.load_pem_private_key(data, password=None)
    except TypeError:
        key = serialization.load_pem_private_key(data, password=getpass.getpass('PEM password: ').encode())
    if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(key.curve, ec.SECP256R1):
        raise ValueError('Only ES256 / P-256 private keys are supported')
    return key


def decode_base64(value):
    return base64.urlsafe_b64decode(value + '=' * (-len(value) % 4))


def load_bitwarden(path, rp):
    vault = json.loads(path.read_text())
    if vault.get('encrypted'):
        raise ValueError('Use a locally decrypted Bitwarden JSON export')
    matches = [credential for item in vault.get('items', [])
               for credential in (item.get('login') or {}).get('fido2Credentials', []) or []
               if credential.get('rpId') == rp]
    if len(matches) != 1:
        raise ValueError('Expected exactly one passkey for the specified RP')
    credential = matches[0]
    key = serialization.load_der_private_key(decode_base64(credential['keyValue']), password=None)
    if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(key.curve, ec.SECP256R1):
        raise ValueError('Only ES256 / P-256 private keys are supported')
    encoded_id = credential['credentialId']
    credential_id = decode_base64(encoded_id[4:]) if encoded_id.startswith('b64.') else uuid.UUID(encoded_id).bytes
    return key, decode_base64(credential['userHandle']), credential_id, int(credential['counter'])


def make_packet(key, rp, user_id, credential_id, counter):
    if not re.fullmatch(r'[a-z0-9.-]{1,127}', rp):
        raise ValueError('RP must be a lowercase ASCII domain, not a URL')
    if not 1 <= len(user_id) <= 64 or not 1 <= len(credential_id) <= 128:
        raise ValueError('Invalid user or credential ID length')
    if not 0 <= counter < 0xffffffff:
        raise ValueError('Counter must be between 0 and 4294967294')
    scalar = key.private_numbers().private_value.to_bytes(32, 'big')
    payload = bytes([len(rp), len(user_id), len(credential_id)]) + counter.to_bytes(4, 'big')
    payload += scalar + rp.encode('ascii') + user_id + credential_id
    return b'DFI1' + len(payload).to_bytes(2, 'big') + payload


def wait_marker(port, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        line = port.readline().strip()
        if b'FATAL ERROR' in line:
            raise RuntimeError('Device firmware stopped; no successful import was reported')
        if line.startswith(b'DFI:'):
            print(line.decode('ascii', errors='replace') if not line.startswith(b'DFI:OK:') else 'DFI:OK', flush=True)
            return line
    raise TimeoutError('Device did not respond; retry after a normal RESET (do not hold BOOT during RESET)')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--pem', type=Path)
    source.add_argument('--bitwarden', type=Path, help='local JSON export; imports only the specified RP')
    parser.add_argument('--rp', required=True)
    parser.add_argument('--user-id', help='user handle in hexadecimal')
    parser.add_argument('--credential-id', help='optional existing credential ID in hexadecimal')
    parser.add_argument('--counter', type=int, default=0)
    parser.add_argument('--port', default='/dev/cu.usbmodem4101')
    parser.add_argument('--output', type=Path, required=True, help='public test metadata; must not exist')
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError('Preserving existing metadata file')
    if args.bitwarden:
        if args.user_id or args.credential_id or args.counter:
            parser.error('Bitwarden import uses the exported IDs and counter')
        key, user_id, credential_id, args.counter = load_bitwarden(args.bitwarden, args.rp)
    else:
        if not args.user_id:
            parser.error('--user-id is required with --pem')
        key = load_key(args.pem)
        user_id = bytes.fromhex(args.user_id)
        credential_id = bytes.fromhex(args.credential_id) if args.credential_id else os.urandom(32)
    packet = make_packet(key, args.rp, user_id, credential_id, args.counter)
    point = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    cose = {1: 2, 3: -7, -1: 1, -2: point[1:33], -3: point[33:]}
    record = {'rp': args.rp, 'id': credential_id.hex(), 'public_key': cbor2.dumps(cose).hex(), 'counter': args.counter}
    # Save only public recovery metadata before sending, in case USB disconnects after storage.
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as output:
        json.dump(record, output, indent=2); output.write('\n')
    print('Connecting over USB. If needed, press RESET without holding BOOT.', flush=True)
    with serial.Serial(args.port, 115200, timeout=.2) as port:
        port.dtr = False
        port.rts = False
        if wait_marker(port, 15) != b'DFI:READY':
            raise RuntimeError('Device is not in USB import mode')
        # USB Serial/JTAG has a small RX FIFO; pace chunks while firmware polls.
        for offset in range(0, len(packet), 16):
            port.write(packet[offset:offset + 16]); port.flush()
            time.sleep(.01)
        packet = None
        marker = wait_marker(port, 15)
        if marker != b'DFI:CONFIRM':
            raise RuntimeError('Import rejected; existing credentials were preserved')
        print(f'Check RP on OLED: {args.rp}. Press BOOT to approve the import.', flush=True)
        result = wait_marker(port, 155)
        if result.startswith(b'DFI:ERROR:'):
            raise RuntimeError('Device rejected import (errno ' + result.decode().split(':')[-1] + ')')
        if result != b'DFI:OK:' + point.hex().encode('ascii'):
            raise RuntimeError('Import failed or returned a different public key; keep public metadata for diagnosis')
    print('Imported key public point verified. Public metadata saved; device restarts into BLE mode.')


if __name__ == '__main__':
    main()
