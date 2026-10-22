"""Encrypt/decrypt a full flash image; decryption does not flash the device."""
import argparse
import hashlib
import json
import os
from pathlib import Path
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b'DIYFIDO-BACKUP-1\n'


def private_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as output:
        output.write(data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['encrypt', 'decrypt'])
    parser.add_argument('input', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--key', type=Path, required=True)
    parser.add_argument('--size-mb', type=int, default=4,
                        help='Expected full flash size in MiB (default: 4)')
    args = parser.parse_args()
    expected = args.size_mb * 1024 * 1024
    data = args.input.read_bytes()
    if args.command == 'encrypt':
        if len(data) != expected:
            raise ValueError(f'Expected the complete {args.size_mb}MB flash image')
        key = AESGCM.generate_key(bit_length=256)
        nonce = os.urandom(12)
        encrypted = MAGIC + nonce + AESGCM(key).encrypt(nonce, data, MAGIC)
        # Authenticate and verify the exact plaintext before writing the backup.
        recovered = AESGCM(key).decrypt(nonce, encrypted[len(MAGIC) + 12:], MAGIC)
        if recovered != data:
            raise ValueError('Backup verification failed')
        private_write(args.key, key)
        private_write(args.output, encrypted)
        print(json.dumps({'size': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
                          'encryption': 'AES-256-GCM', 'verified': True}))
    else:
        if not data.startswith(MAGIC):
            raise ValueError('Unsupported backup format')
        nonce = data[len(MAGIC):len(MAGIC) + 12]
        plaintext = AESGCM(args.key.read_bytes()).decrypt(nonce, data[len(MAGIC) + 12:], MAGIC)
        if len(plaintext) != expected:
            raise ValueError('Unexpected flash image size')
        private_write(args.output, plaintext)
        print(f'Decrypted authenticated {args.size_mb}MB image; device was not written.')


if __name__ == '__main__':
    main()
