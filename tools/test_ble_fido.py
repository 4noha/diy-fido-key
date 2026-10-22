"""Host transport and signature validation tests (no hardware required)."""
import hashlib
import unittest

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from tools.ble_fido_test import RP, Transport, check_auth_data, fragments, public_key


class FramingTests(unittest.TestCase):
    def test_round_trip_boundaries(self):
        for size in (20, 64, 512):
            for length in (0, 1, size - 3, size - 2, 40, 1024):
                with self.subTest(size=size, length=length):
                    payload = bytes(i % 256 for i in range(length))
                    transport = Transport(None)
                    for frame in fragments(0x83, payload, size):
                        transport.notify(None, frame)
                    self.assertEqual(transport.queue.get_nowait(), (0x83, payload))

    def test_reject_bad_sequence(self):
        transport = Transport(None)
        transport.notify(None, b"\x83\x00\x03a")
        transport.notify(None, b"\x01bc")
        self.assertIsInstance(transport.queue.get_nowait(), ValueError)

    def test_reject_overlong_response(self):
        transport = Transport(None)
        transport.notify(None, b"\x83\x00\x01ab")
        self.assertIsInstance(transport.queue.get_nowait(), ValueError)

    def test_reject_missing_initial_fragment(self):
        transport = Transport(None)
        transport.notify(None, b"\x00abc")
        self.assertIsInstance(transport.queue.get_nowait(), ValueError)

    def test_reject_oversized_frame(self):
        transport = Transport(None)
        transport.notify(None, b"\x83\xff\xff")
        self.assertIsInstance(transport.queue.get_nowait(), ValueError)


class ValidationTests(unittest.TestCase):
    def test_presence_and_rp_are_required(self):
        auth = hashlib.sha256(RP.encode()).digest() + b"\x01\x00\x00\x00\x02"
        self.assertEqual(check_auth_data(auth), 2)
        with self.assertRaises(ValueError):
            check_auth_data(b"\x00" * 32 + auth[32:])
        with self.assertRaises(ValueError):
            check_auth_data(auth[:32] + b"\x00" + auth[33:])

    def test_signature_rejects_changed_challenge(self):
        private = ec.generate_private_key(ec.SECP256R1())
        numbers = private.public_key().public_numbers()
        key = public_key({1: 2, 3: -7, -1: 1,
                          -2: numbers.x.to_bytes(32, "big"),
                          -3: numbers.y.to_bytes(32, "big")})
        signature = private.sign(b"authenticator data + challenge", ec.ECDSA(hashes.SHA256()))
        key.verify(signature, b"authenticator data + challenge", ec.ECDSA(hashes.SHA256()))
        with self.assertRaises(InvalidSignature):
            key.verify(signature, b"authenticator data + different", ec.ECDSA(hashes.SHA256()))


if __name__ == "__main__":
    unittest.main()
