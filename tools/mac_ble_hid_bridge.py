"""Forward macOS virtual FIDO HID to the paired C3 using the Apple entitlement."""
import argparse
import asyncio
import base64
import contextlib
import json
import sys
from pathlib import Path
from bleak import BleakClient, BleakScanner
from ble_fido_test import Transport, SERVICE, CONTROL, fragments
from mac_hid_protocol import HIDBridge


class BLEBackend:
    def __init__(self, transport):
        self.transport = transport
        self.unhealthy = False

    async def exchange(self, payload, keepalive):
        if self.unhealthy:
            raise RuntimeError('BLE transport needs reconnecting')
        for frame in fragments(0x83, payload, self.transport.size):
            await self.transport.client.write_gatt_char(CONTROL, frame, response=True)
        deadline = asyncio.get_running_loop().time() + 45
        try:
            while True:
                result = await asyncio.wait_for(self.transport.queue.get(), deadline - asyncio.get_running_loop().time())
                if isinstance(result, Exception):
                    raise result
                command, data = result
                if command == 0x82:
                    await keepalive(data)
                elif command == 0x83:
                    return data
                else:
                    raise RuntimeError('Unexpected BLE response')
        except BaseException:
            # An incomplete transaction must never become the next caller's response.
            self.unhealthy = True
            raise

    async def cancel(self):
        if self.transport.client.is_connected:
            await self.transport.client.write_gatt_char(CONTROL, b'\xbe\x00\x00', response=True)


async def run(args):
    process = await asyncio.create_subprocess_exec(str(args.helper), stdin=asyncio.subprocess.PIPE,
                                                  stdout=asyncio.subprocess.PIPE)
    bridge = None
    timer = None
    try:
        first = await asyncio.wait_for(process.stdout.readline(), 10)
        event = json.loads(first) if first else {}
        if event.get('event') != 'prepared':
            raise RuntimeError('macOS denied virtual HID creation. Sign with a profile granting com.apple.developer.hid.virtual.device.')
        device = await BleakScanner.find_device_by_filter(
            lambda device, ad: device.address == args.device if args.device else device.name == 'DIY FIDO C3' and SERVICE in ad.service_uuids,
            timeout=15)
        if device is None:
            raise RuntimeError('Paired DIY FIDO C3 was not found')
        disconnected = asyncio.Event()
        async with BleakClient(device, timeout=60, disconnected_callback=lambda _: disconnected.set()) as client:
            transport = Transport(client)
            await transport.start()  # authenticated link, notify subscription and CTAP2 revision.
            async def send(report):
                process.stdin.write(json.dumps({'input': base64.b64encode(report).decode('ascii')}).encode() + b'\n')
                await process.stdin.drain()
            bridge = HIDBridge(BLEBackend(transport), send)
            async def expire():
                while True:
                    await asyncio.sleep(.1)
                    await bridge.expire()
            timer = asyncio.create_task(expire())
            process.stdin.write(b'{"activate":true}\n')
            await process.stdin.drain()
            while client.is_connected:
                read_task = asyncio.create_task(process.stdout.readline())
                disconnect_task = asyncio.create_task(disconnected.wait())
                done, pending = await asyncio.wait([read_task, disconnect_task], return_when=asyncio.FIRST_COMPLETED)
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                if disconnect_task in done:
                    raise RuntimeError('BLE disconnected; restart the bridge to reconnect')
                line = read_task.result()
                if not line:
                    raise RuntimeError('Native HID helper exited')
                event = json.loads(line)
                if event.get('event') == 'output':
                    report = base64.b64decode(event['data'], validate=True)
                    await bridge.feed(report)
                elif event.get('event') == 'ready':
                    print('Virtual HID published and BLE connected. Use Chrome; approve requests with BOOT.', flush=True)
                elif event.get('event') == 'error':
                    raise RuntimeError('Native HID report delivery failed')
            raise RuntimeError('BLE disconnected; restart the bridge to reconnect')
    finally:
        if timer:
            timer.cancel()
            await asyncio.gather(timer, return_exceptions=True)
        if bridge:
            with contextlib.suppress(Exception):
                await bridge.close()
        if process.stdin:
            process.stdin.close()
        try:
            await asyncio.wait_for(process.wait(), 3)
        except asyncio.TimeoutError:
            process.terminate()
            await process.wait()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--helper', type=Path, default=Path(__file__).resolve().parents[1] / 'build/mac-bridge/hid_host')
    parser.add_argument('--device', help='specific macOS BLE device UUID')
    try:
        asyncio.run(run(parser.parse_args()))
    except KeyboardInterrupt:
        pass
    except Exception as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
