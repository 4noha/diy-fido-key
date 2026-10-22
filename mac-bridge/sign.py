"""Package and sign only with an already-authorized macOS virtual HID profile."""
import argparse
import datetime
import plistlib
import shutil
import subprocess
from pathlib import Path

ENTITLEMENT = 'com.apple.developer.hid.virtual.device'


def validate_profile(profile):
    allowed = profile.get('Entitlements', {})
    if allowed.get(ENTITLEMENT) is not True:
        raise ValueError('The provisioning profile does not grant virtual HID access')
    if not set(profile.get('Platform', [])).intersection({'OSX', 'macOS'}):
        raise ValueError('A macOS provisioning profile is required')
    expiry = profile.get('ExpirationDate')
    if not expiry or expiry.replace(tzinfo=datetime.timezone.utc) <= datetime.datetime.now(datetime.timezone.utc):
        raise ValueError('The provisioning profile is expired')
    app_key = 'com.apple.application-identifier' if 'com.apple.application-identifier' in allowed else 'application-identifier'
    app_id = allowed.get(app_key, '')
    if '.' not in app_id or '*' in app_id:
        raise ValueError('An explicit application identifier is required')
    bundle_id = app_id.split('.', 1)[1]
    team_id = allowed.get('com.apple.developer.team-identifier')
    if not team_id:
        raise ValueError('The profile must include the signing team identifier')
    return bundle_id, {ENTITLEMENT: True, app_key: app_id, 'com.apple.developer.team-identifier': team_id}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', type=Path, required=True)
    parser.add_argument('--identity', required=True, help='Apple Development signing identity or certificate fingerprint')
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    result = subprocess.run(['security', 'cms', '-D', '-i', str(args.profile)], check=True, capture_output=True)
    bundle_id, entitlements = validate_profile(plistlib.loads(result.stdout))
    subprocess.run(['sh', str(repo / 'mac-bridge/build.sh')], check=True)
    app = repo / 'build/mac-bridge/DIYFIDOBridge.app'
    contents = app / 'Contents'
    (contents / 'MacOS').mkdir(parents=True, exist_ok=True)
    shutil.copy2(repo / 'build/mac-bridge/hid_host', contents / 'MacOS/hid_host')
    shutil.copy2(args.profile, contents / 'embedded.provisionprofile')
    info = {'CFBundleIdentifier': bundle_id, 'CFBundleExecutable': 'hid_host',
            'CFBundleName': 'DIY FIDO BLE Bridge', 'CFBundlePackageType': 'APPL',
            'CFBundleVersion': '1', 'CFBundleShortVersionString': '0.1',
            'LSUIElement': True, 'LSMinimumSystemVersion': '12.0'}
    (contents / 'Info.plist').write_bytes(plistlib.dumps(info))
    entitlement_file = repo / 'build/mac-bridge/authorized-entitlements.plist'
    entitlement_file.write_bytes(plistlib.dumps(entitlements))
    subprocess.run(['codesign', '--force', '--sign', args.identity, '--entitlements',
                    str(entitlement_file), str(app)], check=True)
    subprocess.run(['codesign', '--verify', '--strict', str(app)], check=True)
    print('Signed app built:', app)
    print('Probe:', contents / 'MacOS/hid_host', '--probe')


if __name__ == '__main__':
    main()
