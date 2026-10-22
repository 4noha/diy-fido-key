# HID Virtual Device capability request draft

以下は Apple へ申請するときの説明案。送信していない。専用 App ID、配布範囲、連絡先は申請者が実際の内容に合わせて指定する。

## Purpose

We are developing a macOS research application that bridges a Bluetooth Low Energy FIDO2 authenticator to a virtual HID FIDO authenticator. The BLE device is an ESP32-C3 running Zephyr's FIDO2 subsystem. The application forwards CTAP messages and leaves private-key operations and physical user-presence confirmation on the BLE device.

## Requested capability

`com.apple.developer.hid.virtual.device` for the macOS user-space `IOHIDUserDevice` API.

## Why the capability is needed

The browser discovers CTAP authenticators through HID, while its legacy FIDO BLE discovery is unavailable. The application creates a virtual HID collection with usage page 0xF1D0 and usage 1, using 64-byte input and output reports. It forwards the CTAP CBOR requests over an authenticated, encrypted BLE connection and returns the device responses to the HID client.

## Scope and controls

The application creates only a FIDO HID device, not a keyboard or pointing device. It does not synthesize input events, read other HID devices, modify browsers, disable platform security protections, export private keys, or assert user verification on behalf of the authenticator. Physical BOOT-button approval and PIN/UV behavior remain under the authenticator's control. Reports are forwarded in memory and are not logged to disk. The current scope is local research and interoperability testing, not a certified commercial authenticator.
