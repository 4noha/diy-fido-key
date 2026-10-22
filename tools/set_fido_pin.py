#!/usr/bin/env python3
"""Set the CTAP2 PIN on the attached FIDO key.

Run this yourself in a terminal; the PIN is read with getpass and never
printed or logged. The key asks for a touch (BOOT) while the PIN is set.
"""
import getpass
import sys

from fido2.hid import CtapHidDevice
from fido2.ctap2 import Ctap2
from fido2.ctap2.pin import ClientPin, PinProtocolV2


def main():
    devices = list(CtapHidDevice.list_devices())
    if not devices:
        print('No FIDO HID device found. Replug the key.')
        return 1
    device = devices[0]
    print('device:', device.descriptor.product_name,
          f'{device.descriptor.vid:04x}:{device.descriptor.pid:04x}')
    ctap = Ctap2(device)
    client_pin = ClientPin(ctap, PinProtocolV2())

    # GetInfo is authoritative: get_pin_retries() returns 8 even without a PIN.
    if dict(ctap.info.options).get('clientPin'):
        try:
            retries, _ = client_pin.get_pin_retries()
            print('PIN already set; retries left:', retries)
        except Exception:
            print('PIN already set.')
        print('Use change_pin if you want to replace it.')
        return 0

    print('PIN を入力してください（表示されません）。')
    pin = getpass.getpass('new PIN: ')
    if len(pin) < 6:
        print('Use at least 6 characters.')
        return 1
    if pin != getpass.getpass('repeat PIN: '):
        print('PINs do not match.')
        return 1

    print('>>> デバイスが PRESS 表示になったら BOOT を押してください')
    try:
        client_pin.set_pin(pin)
    except Exception as exc:
        print('failed:', type(exc).__name__, exc)
        return 1
    print('PIN set. Chrome からは PIN 入力が求められます。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
