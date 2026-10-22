import unittest
import base64
import json
import tempfile
from pathlib import Path
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from import_fido_key import make_packet, load_bitwarden


class ImportPacketTests(unittest.TestCase):
    def setUp(self):
        self.key = ec.derive_private_key(7, ec.SECP256R1())

    def test_scalar_metadata_and_counter(self):
        packet = make_packet(self.key, 'example.com', b'user', b'id', 41)
        self.assertEqual(packet[:4], b'DFI1')
        self.assertEqual(int.from_bytes(packet[4:6], 'big'), len(packet) - 6)
        self.assertEqual(packet[6:9], bytes([11, 4, 2]))
        self.assertEqual(int.from_bytes(packet[9:13], 'big'), 41)
        self.assertEqual(int.from_bytes(packet[13:45], 'big'), 7)
        self.assertEqual(packet[45:], b'example.comuserid')

    def test_reject_url_or_nul_rp(self):
        for rp in ['https://example.com', 'example.com\0', '', 'x' * 128]:
            with self.assertRaises(ValueError):
                make_packet(self.key, rp, b'user', b'id', 0)

    def test_reject_empty_or_oversized_identifiers(self):
        for user, credential in [(b'', b'id'), (b'x' * 65, b'id'), (b'u', b''), (b'u', b'x' * 129)]:
            with self.assertRaises(ValueError):
                make_packet(self.key, 'example.com', user, credential, 0)

    def test_reject_counter_overflow(self):
        for counter in [-1, 0xffffffff]:
            with self.assertRaises(ValueError):
                make_packet(self.key, 'example.com', b'u', b'id', counter)


    def test_bitwarden_preserves_ids_and_key(self):
        encoded = base64.urlsafe_b64encode(self.key.private_bytes(
            serialization.Encoding.DER, serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption())).decode().rstrip('=')
        credential = {'rpId': 'example.com', 'keyValue': encoded,
                      'credentialId': '00112233-4455-4677-8899-aabbccddeeff',
                      'userHandle': 'dXNlcg', 'counter': '12'}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'vault.json'
            path.write_text(json.dumps({'items': [{'login': {'fido2Credentials': [credential]}}]}))
            key, user, credential_id, counter = load_bitwarden(path, 'example.com')
            self.assertEqual(key.private_numbers().private_value, 7)
            self.assertEqual(user, b'user')
            self.assertEqual(credential_id.hex(), '00112233445546778899aabbccddeeff')
            self.assertEqual(counter, 12)
            credential['credentialId'] = 'b64.AQIDBA'
            path.write_text(json.dumps({'items': [{'login': {'fido2Credentials': [credential]}}]}))
            self.assertEqual(load_bitwarden(path, 'example.com')[2], b'\x01\x02\x03\x04')
            with self.assertRaises(ValueError):
                load_bitwarden(path, 'missing.example')


if __name__ == '__main__':
    unittest.main()
