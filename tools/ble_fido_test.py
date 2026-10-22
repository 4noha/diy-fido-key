#!/usr/bin/env python3
"""Exercise CTAP2 over encrypted BLE with the DIY FIDO C3 research firmware.

Uses a dedicated test RP; never asks for a real account password or credential.
"""
import argparse
import asyncio
import hashlib
import io
import json
import os
from pathlib import Path

import cbor2
from bleak import BleakClient, BleakScanner
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

SERVICE = "0000fffd-0000-1000-8000-00805f9b34fb"
CONTROL = "f1d0fff1-deaa-ecee-b42f-c9ba7ed623bb"
STATUS = "f1d0fff2-deaa-ecee-b42f-c9ba7ed623bb"
LENGTH = "f1d0fff3-deaa-ecee-b42f-c9ba7ed623bb"
REVISION = "f1d0fff4-deaa-ecee-b42f-c9ba7ed623bb"
RP = "diy-fido-test.invalid"


def fragments(command, payload, size):
    if not 20 <= size <= 512 or len(payload) > 65535:
        raise ValueError("Invalid BLE frame size")
    yield bytes([command]) + len(payload).to_bytes(2, "big") + payload[:size - 3]
    offset, sequence = size - 3, 0
    while offset < len(payload):
        if sequence > 127:
            raise ValueError("Payload exceeds BLE continuation sequence space")
        yield bytes([sequence]) + payload[offset:offset + size - 1]
        offset += size - 1
        sequence += 1


class Transport:
    def __init__(self, client):
        self.client = client
        self.queue = asyncio.Queue()
        self.buffer = bytearray()
        self.command = None
        self.length = 0
        self.sequence = 0

    def notify(self, _, data):
        try:
            if not data:
                raise ValueError("Empty BLE notification")
            if data[0] & 0x80:
                if self.command is not None or len(data) < 3:
                    raise ValueError("Unexpected BLE initialization fragment")
                self.command = data[0]
                self.length = int.from_bytes(data[1:3], "big")
                if self.length > 4096:
                    raise ValueError("Oversized BLE response")
                self.buffer = bytearray(data[3:])
                self.sequence = 0
            else:
                if self.command is None or data[0] != self.sequence:
                    raise ValueError("Invalid BLE fragment sequence")
                self.sequence += 1
                self.buffer.extend(data[1:])
            if len(self.buffer) > self.length:
                raise ValueError("BLE response exceeds declared length")
            if len(self.buffer) == self.length:
                self.queue.put_nowait((self.command, bytes(self.buffer)))
                self.command = None
                self.buffer.clear()
        except ValueError as error:
            self.command = None
            self.buffer.clear()
            self.queue.put_nowait(error)

    async def start(self):
        print("Compare the pairing PIN on Mac and OLED, approve on Mac and press BOOT.", flush=True)
        value = await self.client.read_gatt_char(LENGTH)
        if len(value) != 2:
            raise ValueError("Invalid control-point-length characteristic")
        self.size = min(int.from_bytes(value, "little"), 20)
        revision = await self.client.read_gatt_char(REVISION)
        if not revision or not revision[0] & 0x20:
            raise ValueError("Device does not advertise CTAP2 BLE revision")
        await self.client.start_notify(STATUS, self.notify)
        await self.client.write_gatt_char(REVISION, b"\x20", response=True)

    async def request(self, command, payload):
        for frame in fragments(command, payload, self.size):
            await self.client.write_gatt_char(CONTROL, frame, response=True)
        deadline = asyncio.get_running_loop().time() + 45
        announced_presence = False
        try:
            while True:
                remaining = deadline - asyncio.get_running_loop().time()
                result = await asyncio.wait_for(self.queue.get(), remaining)
                if isinstance(result, Exception):
                    raise result
                cmd, data = result
                if cmd == 0x82:
                    if data == b"\x02" and not announced_presence:
                        print("Waiting for a physical BOOT-button press.", flush=True)
                        announced_presence = True
                    continue
                if cmd == 0xbf:
                    raise RuntimeError(f"BLE protocol error: {data.hex()}")
                if cmd != command:
                    raise ValueError(f"Unexpected BLE response command {cmd:#x}")
                return data
        except asyncio.TimeoutError:
            if self.client.is_connected:
                try:
                    await self.client.write_gatt_char(CONTROL, b"\xbe\x00\x00", response=True)
                except Exception:
                    pass  # Preserve the original request timeout if cancellation fails.
            raise TimeoutError("FIDO request timed out") from None

    async def ctap(self, command, payload=None):
        request = bytes([command])
        if payload is not None:
            request += cbor2.dumps(payload, canonical=True)
        response = await self.request(0x83, request)
        if not response:
            raise ValueError("Empty CTAP response")
        if response[0]:
            raise RuntimeError(f"CTAP error 0x{response[0]:02x}")
        return cbor2.loads(response[1:]) if len(response) > 1 else None


def public_key(cose):
    if cose[1] != 2 or cose[3] != -7 or cose[-1] != 1:
        raise ValueError("Expected ES256/P-256 credential key")
    return ec.EllipticCurvePublicNumbers(
        int.from_bytes(cose[-2], "big"), int.from_bytes(cose[-3], "big"), ec.SECP256R1()
    ).public_key()


def check_auth_data(auth_data):
    if len(auth_data) < 37 or auth_data[:32] != hashlib.sha256(RP.encode()).digest():
        raise ValueError("Invalid authenticator data / RP hash")
    if not auth_data[32] & 1:
        raise ValueError("Physical user presence was not confirmed")
    return int.from_bytes(auth_data[33:37], "big")


async def exercise(args):
    global RP
    RP = args.rp
    device = await BleakScanner.find_device_by_filter(
        lambda device, ad: device.name == "DIY FIDO C3" or SERVICE in ad.service_uuids,
        timeout=15,
    )
    if device is None:
        raise RuntimeError("DIY FIDO C3 was not found")
    print(f"Connecting to {device.name} ({device.address})", flush=True)
    async with BleakClient(device, timeout=60) as client:
        if args.command == "pair":
            print("Approve matching PIN on Mac and OLED; press BOOT. Keeping link open for 60 seconds.", flush=True)
            await asyncio.sleep(60)
            return
        transport = Transport(client)
        await transport.start()
        ping = os.urandom(40)
        if await transport.request(0x81, ping) != ping:
            raise ValueError("Fragmented PING mismatch")
        print("Fragmented BLE PING verified", flush=True)
        info = await transport.ctap(0x04)
        print(f"GetInfo versions={info.get(1)} options={info.get(4)}", flush=True)
        if args.command == "info":
            return
        path = Path(args.credential)
        if args.command == "register":
            if path.exists():
                raise FileExistsError(f"Preserving existing test credential: {path}")
            challenge = os.urandom(32)
            print("Registering test credential: press BOOT when prompted on OLED.", flush=True)
            result = await transport.ctap(0x01, {
                1: challenge, 2: {"id": RP, "name": "DIY FIDO Test"},
                3: {"id": b"diy-test-user", "name": "test", "displayName": "Test User"},
                4: [{"type": "public-key", "alg": -7}], 7: {"rk": True},
            })
            auth_data = result[2]
            counter = check_auth_data(auth_data)
            if not auth_data[32] & 0x40 or len(auth_data) < 55:
                raise ValueError("Missing attested credential data")
            credential_length = int.from_bytes(auth_data[53:55], "big")
            if not credential_length or 55 + credential_length >= len(auth_data):
                raise ValueError("Invalid credential ID length")
            credential_id = auth_data[55:55 + credential_length]
            cose_stream = io.BytesIO(auth_data[55 + credential_length:])
            cose = cbor2.load(cose_stream)
            if result[1] != "packed" or result[3].get("alg") != -7 or "x5c" in result[3]:
                raise ValueError("Expected packed ES256 self attestation")
            public_key(cose).verify(result[3]["sig"], auth_data + challenge, ec.ECDSA(hashes.SHA256()))
            record = {"rp": RP, "id": credential_id.hex(),
                      "public_key": cbor2.dumps(cose).hex(), "counter": counter}
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(record, indent=2) + "\n")
            print("Registration and self-attestation signature verified; test metadata saved.", flush=True)
        record = json.loads(path.read_text())
        if record["rp"] != RP:
            raise ValueError("Test credential belongs to a different RP")
        challenge = os.urandom(32)
        print("Authenticating: press BOOT when prompted on OLED.", flush=True)
        result = await transport.ctap(0x02, {
            1: RP, 2: challenge,
            3: [{"type": "public-key", "id": bytes.fromhex(record["id"])}],
        })
        if result.get(1, {}).get("id") != bytes.fromhex(record["id"]):
            raise ValueError("Assertion used an unexpected credential")
        counter = check_auth_data(result[2])
        public_key(cbor2.loads(bytes.fromhex(record["public_key"]))).verify(
            result[3], result[2] + challenge, ec.ECDSA(hashes.SHA256())
        )
        if counter <= record["counter"]:
            raise ValueError("Signature counter did not increase")
        record["counter"] = counter
        path.write_text(json.dumps(record, indent=2) + "\n")
        print(f"Assertion signature, RP hash, user-presence flag and counter ({counter}) verified.", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["pair", "info", "register", "authenticate"])
    parser.add_argument("--rp", default=RP, help="RP ID associated with the credential")
    parser.add_argument("--credential", default="backups/ble-test-credential.json")
    asyncio.run(exercise(parser.parse_args()))
