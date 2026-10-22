# macOS BLE → FIDO HID bridge prototype

C3 の秘密鍵を PC に取り出さず、CTAP CBOR を BLE で中継する。Python 側がチャンネル管理・分割/再構成・KEEPALIVE/CANCEL を扱い、BLE 接続・revision 選択が完了してから HID を公開し、Objective-C 側が Apple の `IOHIDUserDevice` API で64バイトの入出力 HID report を渡す。FIDO usage page `0xF1D0` / usage `1`。標準入力/出力の JSON pipe は report の受け渡しのみで、永続保存しない。VID/PID はプロトタイプ用の値で、登録済み USB 製品を意味しない。

## 現状

- macOS 26.5 / Apple Silicon、Xcode SDK の公開ヘッダーでビルド成功。
- HID の境界値・分割・不正な順序・チャンネル管理・KEEPALIVE・同じチャンネルの CANCEL / INIT 再同期・タイムアウトの自動テスト成功。
- probe は仮想デバイスの IORegistry 公開を確認してから ready を返す。
- 無権限の実機 probe は `virtual_hid_creation_denied`（exit 3）。BLE ブリッジ起動も HID 作成段階で終了する。Chrome の認識・実サービスのログインは未検証。
- この Mac の開発用署名証明書は確認済み。既存の5つのプロファイルには必要な権限が無かった。
- Apple が付与する `com.apple.developer.hid.virtual.device` を含む適切な macOS プロファイルが必要。Developer アカウント登録や証明書だけでは足りない。SIP、AMFI、Gatekeeper を無効にする手順は使わない。

## ビルドと probe

```sh
sh mac-bridge/build.sh
build/mac-bridge/hid_host --probe
.venv/bin/python -m unittest discover -s tools -p 'test_*.py'
```

## 正式な権限と署名

Apple Developer の Certificates, Identifiers & Profiles で、HID Virtual Device capability の付与状態を確認する。未付与なら Capability Requests から申請し、承認後に専用 App ID に対応する macOS development profile を作成・ダウンロードする。

`com.apple.developer.driverkit.family.hid.virtual.device` は別のキーなので代用しない。今回のユーザー空間 API で確認するのは `com.apple.developer.hid.virtual.device`。申請文案は `capability-request.md`。申請・登録・プロファイル作成を自動で行ってはいない。

```sh
.venv/bin/python mac-bridge/sign.py \
  --profile /path/to/authorized-macos.provisionprofile \
  --identity 'Apple Development: YOUR IDENTITY'
build/mac-bridge/DIYFIDOBridge.app/Contents/MacOS/hid_host --probe
.venv/bin/python tools/mac_ble_hid_bridge.py \
  --helper build/mac-bridge/DIYFIDOBridge.app/Contents/MacOS/hid_host
```

署名ツールはプロファイルの仮想 HID 権限・macOS 対象・有効期限・明示的 App ID を確認してからパッケージ化する。勝手な entitlement 追加だけで署名したバイナリは作らない。macOS がユーザーのアクセス許可を求めた場合は、ユーザーが内容を確認して設定する。

## 実機確認の順序

1. 認可された署名付き probe が成功すること。
2. ブリッジを起動し、Mac にペアリング済みの C3 と接続すること。初回は番号照合と BOOT 承認。
3. FIDO HID として見えること、Chrome が GetInfo を取得できること。
4. 実験用 RP で登録・BOOT 確認・認証署名を確認すること。
5. 実サービスは最後に検証する。取り込み鍵のローカル署名成功は、サービスのユーザー検証要件を満たすことや実ログイン成功を保証しない。

## プロトタイプの制約

- BLE は1台を選んで接続し、処理中の CTAP 要求は1件。HID チャンネルは最大8、メッセージは1024バイト。GETINFO の現行最大サイズに合わせる。
- BLE 切断時は終了し、再起動が必要。転送エラーで不完全な応答が残った場合は次の要求に流用せず、再接続が必要になる。
- ファームウェアのユーザー確認と PIN/UV の挙動をそのまま使う。PC 側で BOOT 承認や UV フラグを偽造しない。
- 常駐インストール、ログイン項目への追加、管理者権限での実行は行っていない。

参照: [Apple IOHIDUserDevice API](https://developer.apple.com/documentation/iokit/3334952-iohiduserdevicecreatewithpropert)、[仮想HID entitlement](https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.developer.hid.virtual.device)、[Apple の権限確認実装](https://github.com/apple-oss-distributions/IOHIDFamily/blob/main/IOHIDFamily/IOHIDResourceUserClient.cpp)、[管理対象 capability](https://developer.apple.com/help/account/capabilities/capability-requests)。PoneBiometrics/fido2ble の Linux ブリッジ構成を参考にした独自実装で、Linux 専用コードはコピーしていない。
