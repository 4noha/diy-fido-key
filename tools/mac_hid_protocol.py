"""Bounded CTAPHID framing and BLE forwarding; never stores or exports keys."""
import asyncio
import secrets
import time

BROADCAST = 0xffffffff
INIT, PING, CBOR, CANCEL, KEEPALIVE, ERROR = 6, 1, 0x10, 0x11, 0x3b, 0x3f
MAX_MESSAGE = 1024


def reports(cid, command, payload):
    if not 0 <= cid <= BROADCAST or not 0 <= command < 128 or len(payload) > MAX_MESSAGE:
        raise ValueError('Invalid HID message')
    prefix = cid.to_bytes(4, 'big')
    yield (prefix + bytes([command | 0x80]) + len(payload).to_bytes(2, 'big') + payload[:57]).ljust(64, b'\0')
    for sequence, offset in enumerate(range(57, len(payload), 59)):
        yield (prefix + bytes([sequence]) + payload[offset:offset + 59]).ljust(64, b'\0')


class HIDBridge:
    def __init__(self, backend, send, clock=time.monotonic):
        self.backend, self.send, self.clock = backend, send, clock
        self.channels = set()
        self.partial = {}
        self.pending = None
        self.active_cid = None
        self.suppress_reply = False

    async def reply(self, cid, command, payload):
        for report in reports(cid, command, payload):
            await self.send(report)

    async def error(self, cid, code):
        await self.reply(cid, ERROR, bytes([code]))

    async def expire(self):
        for cid, value in list(self.partial.items()):
            if self.clock() - value[4] > 3:
                del self.partial[cid]
                await self.error(cid, 5)

    async def feed(self, report):
        if len(report) != 64:
            raise ValueError('Expected a 64-byte HID output report')
        cid, tag = int.from_bytes(report[:4], 'big'), report[4]
        if cid == 0 or (cid == BROADCAST and tag != (INIT | 0x80)):
            await self.error(cid, 0x0b); return
        if cid != BROADCAST and cid not in self.channels:
            await self.error(cid, 0x0b); return
        if self.active_cid is not None and tag not in (INIT | 0x80, CANCEL | 0x80):
            await self.error(cid, 6); return
        if tag & 0x80:
            command, length = tag & 0x7f, int.from_bytes(report[5:7], 'big')
            if command not in (INIT, PING, CBOR, CANCEL):
                await self.error(cid, 1); return
            if length > MAX_MESSAGE or (command == INIT and length != 8) or (command == CANCEL and length != 0) or (command == CBOR and length == 0):
                await self.error(cid, 3); return
            if cid in self.partial and command not in (INIT, CANCEL):
                del self.partial[cid]
                await self.error(cid, 4); return
            self.partial.pop(cid, None)
            body = bytearray(report[7:7 + min(length, 57)])
            self.partial[cid] = [command, length, body, 0, self.clock()]
        else:
            if cid not in self.partial or self.partial[cid][3] != tag:
                self.partial.pop(cid, None)
                await self.error(cid, 4); return
            value = self.partial[cid]
            value[2].extend(report[5:5 + min(value[1] - len(value[2]), 59)])
            value[3] += 1
            value[4] = self.clock()
        value = self.partial[cid]
        if len(value[2]) == value[1]:
            del self.partial[cid]
            await self.message(cid, value[0], bytes(value[2]))

    async def message(self, cid, command, payload):
        if command == INIT:
            if self.active_cid == cid:
                self.suppress_reply = True
                await self.backend.cancel()
                try:
                    await asyncio.wait_for(asyncio.shield(self.pending), 3)
                except asyncio.TimeoutError:
                    await self.error(cid, 6); return
            if cid == BROADCAST:
                if len(self.channels) >= 8:
                    await self.error(cid, 6); return
                assigned = secrets.randbelow(BROADCAST - 1) + 1
                while assigned in self.channels:
                    assigned = secrets.randbelow(BROADCAST - 1) + 1
                self.channels.add(assigned)
            else:
                assigned = cid
            # INIT protocol v2, prototype version 0.1.0, CBOR and NMSG capabilities.
            await self.reply(cid, INIT, payload + assigned.to_bytes(4, 'big') + bytes([2, 0, 1, 0, 0x0c]))
        elif command == CANCEL:
            if self.active_cid == cid:
                await self.backend.cancel()  # CANCEL has no HID response of its own.
        elif command == PING:
            await self.reply(cid, PING, payload)
        elif command == CBOR:
            if self.active_cid is not None:
                await self.error(cid, 6); return
            self.active_cid, self.suppress_reply = cid, False
            self.pending = asyncio.create_task(self.exchange(cid, payload))

    async def exchange(self, cid, payload):
        async def keepalive(value):
            if not self.suppress_reply:
                await self.reply(cid, KEEPALIVE, value)
        try:
            response = await self.backend.exchange(payload, keepalive)
            if not self.suppress_reply:
                if not response or len(response) > MAX_MESSAGE:
                    await self.error(cid, 3)
                else:
                    await self.reply(cid, CBOR, response)
        except (asyncio.TimeoutError, TimeoutError):
            if not self.suppress_reply:
                await self.error(cid, 5)
        except Exception:
            if not self.suppress_reply:
                await self.error(cid, 0x7f)
        finally:
            self.active_cid = None

    async def close(self):
        if self.pending:
            self.suppress_reply = True
            if not self.pending.done():
                try:
                    await self.backend.cancel()
                finally:
                    self.pending.cancel()
            await asyncio.gather(self.pending, return_exceptions=True)
