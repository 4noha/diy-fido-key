import asyncio
import unittest
from mac_hid_protocol import HIDBridge, reports, BROADCAST, INIT, CBOR, PING, CANCEL, ERROR, KEEPALIVE


class Backend:
    def __init__(self):
        self.calls = []
        self.cancels = 0
        self.hold = False
        self.release = asyncio.Event()

    async def exchange(self, payload, keepalive):
        self.calls.append(payload)
        await keepalive(b'\x02')
        if self.hold:
            await self.release.wait()
            return b'\x2d'
        return b'\x00' + payload

    async def cancel(self):
        self.cancels += 1
        self.release.set()


class BridgeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.backend = Backend()
        self.sent = []
        self.now = 0
        async def send(report):
            self.sent.append(report)
        self.bridge = HIDBridge(self.backend, send, lambda: self.now)

    async def asyncTearDown(self):
        await self.bridge.close()

    async def init(self):
        nonce = b'12345678'
        await self.bridge.feed(next(reports(BROADCAST, INIT, nonce)))
        report = self.sent.pop()
        self.assertEqual(report[7:15], nonce)
        self.assertEqual(report[19:24], bytes([2, 0, 1, 0, 0x0c]))
        return int.from_bytes(report[15:19], 'big')

    async def feed_message(self, cid, command, payload):
        for frame in reports(cid, command, payload):
            await self.bridge.feed(frame)
        await asyncio.sleep(0)

    async def test_framing_roundtrip_boundaries(self):
        cid = await self.init()
        for size in [0, 57, 58, 116, 1024]:
            payload = bytes(i % 251 for i in range(size))
            await self.feed_message(cid, PING, payload)
            output = self.sent.copy(); self.sent.clear()
            self.assertTrue(all(len(frame) == 64 for frame in output))
            reconstructed = output[0][7:7 + min(size, 57)] + b''.join(frame[5:] for frame in output[1:])
            self.assertEqual(reconstructed[:size], payload)

    async def test_fragmented_cbor_and_keepalive(self):
        cid = await self.init()
        payload = b'x' * 300
        await self.feed_message(cid, CBOR, payload)
        await self.bridge.pending
        self.assertEqual(self.backend.calls, [payload])
        self.assertEqual(self.sent[0][4], KEEPALIVE | 0x80)
        self.assertEqual(self.sent[0][7], 2)
        self.assertEqual(self.sent[1][4], CBOR | 0x80)

    async def test_invalid_channel_never_reaches_ble(self):
        await self.feed_message(77, CBOR, b'\x04')
        self.assertEqual(self.sent[-1][4:8], bytes([ERROR | 0x80, 0, 1, 0x0b]))
        self.assertFalse(self.backend.calls)

    async def test_bad_sequence_and_oversized_message(self):
        cid = await self.init()
        frames = list(reports(cid, CBOR, b'x' * 100))
        await self.bridge.feed(frames[0])
        bad = bytearray(frames[1]); bad[4] = 1
        await self.bridge.feed(bytes(bad))
        self.assertEqual(self.sent[-1][7], 4)
        bad = bytearray(next(reports(cid, CBOR, b'x'))); bad[5:7] = (1025).to_bytes(2, 'big')
        await self.bridge.feed(bytes(bad))
        self.assertEqual(self.sent[-1][7], 3)
        self.assertFalse(self.backend.calls)

    async def test_cancel_only_own_channel_and_busy(self):
        first, second = await self.init(), await self.init()
        self.backend.hold = True
        await self.feed_message(first, CBOR, b'\x04')
        await self.feed_message(second, CANCEL, b'')
        self.assertEqual(self.backend.cancels, 0)
        await self.feed_message(second, CBOR, b'\x04')
        self.assertEqual(self.sent[-1][7], 6)
        await self.feed_message(first, CANCEL, b'')
        await self.bridge.pending
        self.assertEqual(self.backend.cancels, 1)
        self.assertEqual(self.sent[-1][4], CBOR | 0x80)
        self.assertEqual(self.sent[-1][7], 0x2d)

    async def test_init_resync_discards_prior_response(self):
        cid = await self.init()
        self.backend.hold = True
        await self.feed_message(cid, CBOR, b'\x04')
        self.sent.clear()
        await self.feed_message(cid, INIT, b'abcdefgh')
        self.assertEqual(self.backend.cancels, 1)
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.sent[0][4], INIT | 0x80)

    async def test_partial_timeout(self):
        cid = await self.init()
        await self.bridge.feed(next(reports(cid, CBOR, b'x' * 100)))
        self.now = 4
        await self.bridge.expire()
        self.assertEqual(self.sent[-1][7], 5)
        self.assertFalse(self.backend.calls)

    async def test_channel_limit(self):
        for _ in range(8):
            await self.init()
        await self.feed_message(BROADCAST, INIT, b'12345678')
        self.assertEqual(self.sent[-1][7], 6)


if __name__ == '__main__':
    unittest.main()
