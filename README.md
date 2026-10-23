# diy-fido-key

市販の安い ESP32 ボードを `pico-fido` ファームウェアで焼いて作る、USB 接続の
FIDO2/WebAuthn パスキーデバイス（自作 YubiKey）。

出典: <https://www.makeuseof.com/made-own-yubikey-less-than-8/>

## 対象ハードウェア / 前提

- **ESP32-S2 または ESP32-S3**（USB-OTG デバイスモードが必須）
- ⚠ **ESP32-C3・無印 ESP32・C6・H2 は不可**（USB-OTG ペリフェラルが無い）
- ブラウザ（`picokeys.com/esp32-flasher/` の Web 書き込みツール用）

## できること

`pico-fido` の機能一式（CTAP 2.3 / CTAP 1 / WebAuthn / U2F / ECDSA・EdDSA 複数曲線 /
YubiKey 風 OTP エミュレーション）を、PC から見て本物の USB セキュリティキーとして使う。

## セットアップ

```
1. ESP32-S2/S3 ボードを用意（$6〜8 程度）
2. https://picokeys.com/esp32-flasher/ を開く
3. BOOT+RESET でブートローダに入れてブラウザから接続
4. ファームウェア「Pico Fido」を選んで書き込み
5. PC に挿すと HID オーセンティケータとして認識される
6. PicoKey App で VID/PID をパッチ（OpenSC/ykman/GnuPG との互換用）
```

## 制約

- **FIDO 認証なし・セキュアエレメントなし。** 個人用途・実験用・バックアップ鍵に限定
- ファームウェアは **AGPLv3**

## ESP32-S3 + ST7735 LCD（2026-10-22〜）

USB-OTG を持つ実機として **ESP32-S3 ボード（0.96inch ST7735 80×160 IPS 付き）** を追加。

- SoC: ESP32-S3 (QFN56) rev v0.2 / Flash 16MB / PSRAM 8MB / native USB
- USB シリアルは MAC 由来
- LCD: ST7735S 80×160、`SPI2_HOST`、SCLK=10 / MOSI=11 / CS=12 / DC=13 / RST=14
- BOOT ボタン = **GPIO0**（基板裏）。起動時に押したままだと **ROM ダウンロードモードに固定**される
- 元の 16MB フラッシュは `backups/esp32s3-original-20261022.aesgcm`（鍵は `~/.config/diy-fido-key/backup-keys/`、Git 対象外）

### ビルドと書き込み

ESP-IDF **v5.5.1**（upstream CI と同じ）でビルドする。`vendor/pico-fido` は Git 対象外。

```sh
git clone https://github.com/polhenarejos/pico-fido vendor/pico-fido
git -C vendor/pico-fido submodule update --init --recursive
. ~/esp/esp-idf-v5.5.1/export.sh
sh tools/build-pico-fido-esp32s3.sh          # LCD パッチ適用 + build + merge
esptool --chip esp32s3 --port /dev/cu.usbmodemXXXX write-flash 0x0 build/pico-fido-esp32s3/pico_fido_full.bin
```

ダウンロードモードは **BOOT(GPIO0) を押したまま USB を挿す**。書き込み後は BOOT を離して
USB を挿し直す（押したままだと起動しない）。

### LCD 設定（実機で確定）

- `MADCTL 0x08`（BGR）/ オフセット `col=26, row=1` / **INVON**
- 16bit カラーは **送信前にバイトスワップ必須**（ESP32 はリトルエンディアン、ST7735 は MSB first）。忘れると画像がモザイク状に崩れる
- SPI クロックは **12MHz**（40MHz は ST7735 の仕様超過）
- ベンダーデモは TFT_eSPI の `TFT_eSPI(80,160)` + `setRotation(1)`。160x80 用の `GREENTAB160x80`（26,1 + INVON）に相当
- キャラ画像は `tools/make-lcd-image.py` で白背景を輪郭からフラッドフィルして透過し、`esp32-lcd/mascot_80x80.h` に埋め込む
- 校正用に `-DLCD_CALIBRATION=ON`（向き/オフセット/反転）と `-DLCD_COLOR_CAL=ON`（色順/バイト順）のビルドがある。BOOT 押下で候補を切り替える

### 実測結果（2026-10-22/23）

- `Pico Key`（VID:PID `2E8A:10FE`）として macOS に HID 列挙。CTAP 2.3 / max msg 1024
- `python-fido2` で登録（attestation `packed`、UP+AT）と認証（署名検証、counter 2、UP）に成功
- **Chrome からの WebAuthn も成功**（`tools/webauthn_local_test.py`、RP=`localhost:8787`）: `webauthn.create` → `webauthn.get`（署名 72 bytes、BOOT 承認）。サーバー側に challenge/credential を記録
- LCD にキャラ画像＋状態表示（READY / PRESS BOOT / WORKING）を出す `esp32-lcd/` を追加。色・向き・バイト順は実機で確定済み

### 落とし穴

- **USB-Serial/JTAG のセカンダリコンソールを有効にしたままだと、TinyUSB(OTG) と GPIO19/20 を奪い合い、TG0WDT の起動ループになる。** `CONFIG_ESP_CONSOLE_SECONDARY_NONE=y` にする（ビルドスクリプトが自動適用）
- フラッシュモードは **DIO** で動作確認（公式ビルドと同じ。QIO は未検証）
- 書き込み後に HID として動いている間は `/dev/cu.*` が消えるため、再書き込みは毎回 BOOT+挿し直しが必要

## 現状

- ユーザー指定の **ESP32-C3 + SSD1306 72×40 OLED** を実機テスト中（2026-10-02）。
- PlatformIO / Arduino / U8g2 2.36.15 による書き込み・ハッシュ検証、アプリ起動、OLED 初期化・更新ログを確認済み。ユーザー目視でも枠・文字・数字の正常表示を確認済み。
- OLED: SDA=GPIO5 / SCL=GPIO6 / 0x3C。128×64 バッファ内の `(28,24)` に 72×40 を描画。
- I²C 検出後は `Wire.end()` を呼び、U8g2 に再初期化させる。省略時は OLED 初期化が進まなかった。
- FIDO ファームウェアは未着手。C3 の USB HID 制約を踏まえた移植方法は別途検討。

### 書き込み・OLED テスト

```sh
pio run -t upload
pio device monitor -b 115200
```

`platformio.ini` のポートは `/dev/cu.usbmodem4101`。画面には枠、`ESP32-C3`、`OLED 72x40`、増える数字と動く点を表示する。
書き込み前の 4MB バックアップは `backups/esp32c3-before-test.bin` に保存済み（Git 対象外）。

表示領域の参考: [Tama79 の OLED 実機記事](https://qiita.com/Tama79/items/66047c95ccd0864dd203)。

### FIDO 移植の調査（2026-10-02）

ユーザー提示の Zephyr FIDO2 サンプルを基に **ESP32-C3 向け BLE 版を実装・書き込み中**。下記の pico-fido 固定方針から、BLE を持つ Zephyr FIDO2 サブシステムに切り替えた。認証済みペアリング（security level 4、bond 保存）・分割 PING・GetInfo（FIDO 2.0/2.1）まで実機で確認済み。登録・自己 attestation・認証署名・再起動後の再認証まで専用クライアントで検証済み。

- C3 の内蔵 USB はシリアル/JTAG 固定で HID に変更できない。[Espressif の仕様](https://docs.espressif.com/projects/esp-idf/en/v5.0/esp32c3/api-guides/usb-serial-jtag-console.html)
- 調査用に `vendor/pico-fido` を取得（Git 対象外）。本体 revision `f01fa1e2817a845e44d788f3f633a1f122ce332e`、SDK revision `50699e53e8ada214c27f6c9b66ea3b6f127fc655`。本体 `src/fido/CMakeLists.txt` と SDK の ESP-IDF コンポーネントは `esp_tinyusb` に依存する。BLE の通信処理を追加する必要がある。
- 従来の FIDO BLE は GATT primary service `0xFFFD` を使い、暗号化・ペアリングと CTAP メッセージの分割/再構成が必要。[FIDO CTAP 仕様](https://fidoalliance.org/specs/fido-v2.1-ps-20210615/fido-client-to-authenticator-protocol-v2.1-ps-20210615.html)
- 現行 Chromium の `FidoDiscoveryFactory::Create` は `kBluetoothLowEnergy` で空のリストを返す。従来の BLE キーを広告するだけでは Chrome から直接使えない。`kHybrid` は別の caBLE v2 discovery を使う。[Chromium ソース](https://chromium.googlesource.com/chromium/src/+/main/device/fido/fido_discovery_factory.cc)
- 専用 BLE クライアントによる実機テストを用意した。広告/GetInfo のみでは完成した FIDO 認証器とは扱わず、登録・ボタン確認・署名検証・再起動後の認証までを検証する。

### Zephyr BLE FIDO2

`zephyr-app/` は Zephyr 4.5.0-rc1 の FIDO2 サブシステムを利用する研究用ファームウェア。U8g2 の C API を Zephyr I²C に接続して OLED に状態と BLE ペアリング PIN を表示する。BOOT（GPIO9）の新しい押下でユーザー確認する。ボタンを常時承認にする設定は使わない。

- BLE: `DIY FIDO C3`、FIDO GATT service `0xFFFD`。暗号化だけでなく認証済みペアリングを要求する。Mac と OLED の6桁 PIN が一致すれば Mac 側で承認し、BOOT を押す。入力方式にフォールバックした場合は OLED の PIN を Mac 側へ入力する。
- 最大5台の PC のペアリング情報を保存し、同時接続は1台。各 PC の初回接続で番号照合と BOOT 承認を行う。切り替えるときは使用中の PC のクライアント接続を終了する。6台目のペアリングで既存の情報を自動削除しない。ペアリング削除用のデバイス操作は未実装。5台設定で実機へ書き込み済み。既存 Mac の bond 保持・暗号化再接続・GetInfo・保存済み資格情報の認証署名を確認（カウンター3）。2台目以降の実機ペアリングは未検証。
- CTAP2、ES256、資格情報の永続保存は Zephyr の実装を利用する。資格情報は NVS/settings に保存する。
- OLED は状態変更時だけ更新し、I²C は 400kHz。100kHz で常時更新していた構成では GATT discovery 中に接続タイムアウトが発生し、変更後はペアリング段階まで進んだ。
- 現状はサンプル同様に常時ペアリング可能。実験用に限定する。保存の ITS 鍵導出は Zephyr の device-ID hash 方式で、フラッシュ抽出に対する秘密保護を保証しない。セキュアブートや eFuse の変更はしていない。
- ブラウザとの WebAuthn 連携は未検証。現行 Chromium の従来 BLE 検出は無効なので、専用クライアントの動作とブラウザ連携を混同しない。

```sh
sh tools/setup-zephyr.sh
sh tools/build-zephyr.sh
esptool --port /dev/cu.usbmodem4101 write-flash 0 build/zephyr/zephyr/zephyr.bin
.venv/bin/python tools/ble_fido_test.py info
.venv/bin/python tools/ble_fido_test.py register
# 再起動後、保存した公開鍵と資格情報IDで再認証
.venv/bin/python tools/ble_fido_test.py authenticate
# ハードウェア不要の通信フレーム・署名検証テスト
.venv/bin/python -m unittest tools.test_ble_fido
```

クライアントは実験用 RP `diy-fido-test.invalid` を使用し、登録時の自己 attestation、認証時の署名・RP ハッシュ・UP フラグ・増加するカウンターを検証する。`backups/ble-test-credential.json` は公開鍵と資格情報 ID のみ（秘密鍵はデバイス内）。Mac の Bluetooth 設定に見えなくても、専用クライアントの BLE スキャンで検出されることがある。

元の Arduino OLED テストに戻す場合は `pio run -t upload`。元のプリインストールファームウェアへ戻す場合は、保存済み 4MB イメージを `esptool --port /dev/cu.usbmodem4101 write-flash 0 backups/esp32c3-before-test.bin` で書き込む（デバイス内のテスト資格情報・ペアリング情報も当時の状態へ戻る）。

実機検証（2026-10-02）: 初期設定では RSSI −79〜−81 dBm、接続 timeout (`reason=8`) が発生した。BLE の既定送信出力を +9 dBm に設定し、番号照合の BOOT 検出を入力イベントに変更した後、ペアリング・bond 保存・再接続・分割 PING・GetInfo が成功した。登録要求では最初に暗号処理中の CPU 例外が発生し、FIDO スタックを 4096→8192 bytes に増やして stack sentinel を有効化したところ、例外なくユーザー確認待ちまで進んだ。最初の確認待ちは未押下で CTAP `0x2f`（時間切れ）。その後 BOOT 確認を行い、登録の自己 attestation 署名・認証署名・RP ハッシュ・UP フラグを検証できた。再起動後も同じ資格情報で再認証に成功し、署名カウンターは 1→2 に増加した。`pair` は60秒のペアリング専用テスト。

参照: [Zephyr FIDO2 サンプル](https://docs.zephyrproject.org/latest/samples/subsys/authentication/fido2/README.html)。アプリ独自部分は Apache-2.0、U8g2 と Zephyr は各上流のライセンスに従う。


## ファームウェアを公開・配布する場合

このリポジトリのファームは **pico-fido（AGPLv3）** の派生物です。バイナリを配るなら次を満たしてください。

### 必須

1. **対応するソースの提供**（AGPLv3 §4-6）
   - 本リポジトリのコード + `tools/install-esp32-lcd.sh` が当てるパッチ
   - pico-fido `ade7702` / pico-keys-sdk `a2f0a51` / ESP-IDF `v5.5.1`
   - ビルド手順（`tools/build-pico-fido-esp32s3.sh`）
2. **LICENSE（AGPL-3.0）と NOTICE** を同梱（両方このリポジトリにあり）
3. **変更したファイルへの告知**（著作権表示は削除しない）
4. **VID/PID を自分のものに変更**（下記）

### VID/PID

`2E8A:10FE` は pico-fido 用に Raspberry Pi が付与した ID で、pico-fido の README は
**自分が所有していない VID/PID でバイナリを配布する権利はない**としています。

- **ソースのみ公開する場合**: 既定の `2E8A:10FE` のままで可（利用者が自分の環境でビルドする形。個人利用の範囲）
- **ビルド済みバイナリを配布する場合**: Raspberry Pi の ID を同梱することになるため、自分の VID/PID に変更する

- 個人開発なら [pid.codes](https://pid.codes/) で VID `0x1209` + 固有 PID の割当を受ける
- ビルド時に環境変数で差し替え可能（確認済み）:

```sh
FIDO_USB_VID=0x1209 FIDO_USB_PID=0x0001 sh tools/build-pico-fido-esp32s3.sh
```

- VID/PID を変えると OpenSC / ykman の互換設定が変わるので README に注記する

### 絵（キャラクター）

`esp32-lcd/mascot_80x80.h` は画像そのものを埋め込んでいます。著作者は `NOTICE` に記載しています。

### 免責

「FIDO 認証・セキュアエレメントなし、個人・実験用途、無保証」を明記してください。`YubiKey` や `Pico` を製品名に使わないこと。


## セキュリティプロファイル（ESP32-S3 の保護機能）

`tools/security-profiles.sh` で3段階を切り替えられます。**スクリプトはビルドのみ**を行い、eFuse の書き込みは行いません（実機に触れません）。

| プロファイル | 内容 | 再書き込み | フラッシュ読み出し |
|---|---|---|---|
| `backup`（既定） | 保護なし | 自由 | 可能（現状） |
| `encrypted` | Secure Boot v2（ECDSA P-256）+ Flash Encryption **development** | 署名＋暗号化イメージで可 | 実質不可（鍵は開発モードで読める） |
| `secure` | Secure Boot v2 + Flash Encryption **release** | 署名前提（鍵必須） | 不可 |

```sh
. ~/esp/esp-idf-v5.5.1/export.sh
sh tools/security-profiles.sh backup      # 従来どおり
sh tools/security-profiles.sh encrypted   # 署名 + 暗号化（開発モード）
sh tools/security-profiles.sh secure      # 署名 + 暗号化（リリース）
```

- 署名鍵は `~/.config/diy-fido-key/secure-boot/secure-boot-ecdsa-p256.pem`（0600、リポジトリ外）に生成されます。**オフラインで2箇所に保管してください**
- 出力: `build/pico-fido-<profile>/pico_fido_<profile>.bin` と `FLASH-AND-BURN.md`（eFuse 焼き順）
- Secure Boot を有効にすると署名でブートローダが 32KB を超えるため、**パーティションテーブルは 0x10000** に移動します（マージ済みイメージがその配置を含みます）

### eFuse を焼く前に

- `secure` は **元の無防備な状態に戻せません**（署名済みイメージでの更新のみ可能）
- 署名鍵を失うと更新不能。バックアップを必ず取得
- ダウンロードモードは塞がないこと（復旧経路を残す）
- pico-fido の Secure Lock（MKEK を OTP へ）は Secure Boot 有効後に PicoKey App から実行

## 参考リンク

- 紹介記事: <https://www.makeuseof.com/made-own-yubikey-less-than-8/>
- ファームウェア本体: <https://github.com/polhenarejos/pico-fido>
- Web 書き込みツール: <https://picokeys.com/esp32-flasher/>

### 同じボード向けの暗号化バックアップ

2026-10-02 の現在の全フラッシュ（4MB、ファームウェア・BLE bond・FIDO 資格情報）を `backups/esp32c3-fido-20261002.aesgcm` に AES-256-GCM で保存した。復号鍵は `~/.config/diy-fido-key/backup-keys/esp32c3-fido-20261002.key`。どちらも Git 対象外、ファイル権限600。両方を紛失しないよう別々に保管する。鍵ファイルの内容は共有しない。

`backups/esp32c3-fido-20261002.json` に元イメージの SHA-256、サイズ、ボード MAC と対象コミットを記録。復号後の4MBが元の読み出しと完全一致することを確認し、一時的な平文は削除した。実機への復元書き込みは未検証。

復元が必要になった場合のみ、同じボード（同じボード）へ以下を実施する。現在の資格情報・ペアリング情報・署名カウンターもバックアップ時点へ戻る。復号画像は秘密鍵を含むため、書き込み後に削除する。

```sh
.venv/bin/python tools/flash_backup.py decrypt \
  backups/esp32c3-fido-20261002.aesgcm backups/restore-private.bin \
  --key ~/.config/diy-fido-key/backup-keys/esp32c3-fido-20261002.key
esptool --port /dev/cu.usbmodem4101 write-flash 0 backups/restore-private.bin
rm backups/restore-private.bin
```

電源断でも bond と資格情報はフラッシュに残る。再起動後の認証は検証済み。PC 側のペアリング情報はこのバックアップに含まれない。古いバックアップの復元ではカウンターが戻るため、サービス側で警告や拒否が起きる可能性がある。

### 任意の ES256 秘密鍵を USB から取り込む

`tools/import_fido_key.py` と `zephyr-app/src/key_import.c` を追加。起動後、BLE を開始する前の5秒間だけ USB Serial/JTAG で取り込み要求を受け付ける。要求がなければ通常の BLE モードへ進む。PC ツールがポートを開くと通常はボードがリセットされる。必要なら BOOT を押さず RESET のみを押す（BOOT+RESET は ROM 書き込みモードになる）。

取り込み要求には P-256 秘密スカラー、RP ID、ユーザーハンドル、資格情報 ID、署名カウンターを含める。OLED の RP 表示を確認して新たに BOOT を押すと保存する（確認時間120秒）。取り込み中は BLE/CTAP を起動しない。既存 ID は拒否し、他の資格情報を削除・上書きしない。保存に失敗した場合は新しい PSA 鍵を破棄する。保存後に再起動して BLE に戻る。秘密鍵を USB の応答やログへ出力しない。秘密鍵を含む受信バッファは処理後にゼロ化する。USB 転送自体は暗号化していないため、自分の PC から直接接続して使う。

PEM（PKCS#8 または EC PRIVATE KEY、暗号化 PEM は対話パスワード入力）:

```sh
.venv/bin/python tools/import_fido_key.py --pem /path/to/private-key.pem \
  --rp example.com --user-id 75736572 --output backups/imported-public.json
# 既存資格情報を移植する場合は --credential-id HEX --counter N も指定する
```

Bitwarden の非暗号化 JSON エクスポートから指定 RP のパスキー1件のみを取り込む:

```sh
.venv/bin/python tools/import_fido_key.py --bitwarden /path/to/export.json \
  --rp example.com --output backups/imported-public.json
```

Bitwarden の PKCS#8 DER、Base64URL の userHandle、および GUID / `b64.` の credentialId を解釈し、元の ID とカウンターを保持する。同じ RP に複数の項目がある場合は自動選択せず拒否する。ID の解釈は [Bitwarden credential-id-utils](https://github.com/bitwarden/clients/blob/main/libs/common/src/platform/services/fido2/credential-id-utils.ts) と [guid-utils](https://github.com/bitwarden/clients/blob/main/libs/common/src/platform/services/fido2/guid-utils.ts) に合わせた。

出力 JSON は公開鍵・資格情報 ID・RP・カウンターのみ。取り込み前に保存するため、USB が保存直後に切れても資格情報 ID を失わない。ファイルの存在は取り込み成功を意味しない。成功はデバイスから返った公開点と元の公開鍵の一致で確認する。取り込んだ鍵は PSA の署名用途の永続鍵にし、秘密鍵の個別エクスポート権限は付けない。

```sh
.venv/bin/python tools/ble_fido_test.py authenticate \
  --rp example.com --credential backups/imported-public.json
```

これは専用クライアントのランダムなテスト challenge に対する署名検証であり、実サービスへのログイン成功を示さない。サービスには対応する公開鍵・資格情報 ID が登録済みである必要がある。実サービスを含むブラウザログインは現行の従来 BLE トランスポートでは未対応。旧バックアップは取り込み前の状態なので、新しい鍵を含めたい場合はバックアップを更新する。

USB 取り込み実機検証: テスト用 P-256 PEM の取り込み、公開点の一致、再起動後の BLE 認証署名・RP ハッシュ・UP フラグ・カウンター1を確認。実サービスの Bitwarden 項目も取り込み、公開点の一致・再起動後のローカル認証署名・RP ハッシュ・UP フラグ・カウンター1を確認。同一資格情報IDの再取り込みは EEXIST で拒否され、上書きされないことを実機確認。16バイト等の取り込みIDを扱うため、Zephyr の allow/exclude list 検索を保存済みIDの検索優先に変更した（`patches/zephyr-imported-credential-ids.patch`、ビルド時に自動適用）。RP ハッシュの照合と wrapped ID の復号検証は維持する。

取り込み後の最新バックアップは `backups/esp32c3-fido-after-import-20261002.aesgcm`、対応する復号鍵は `~/.config/diy-fido-key/backup-keys/esp32c3-fido-after-import-20261002.key`。実サービスとテスト用の取り込み資格情報も含む。復号後の4MBと読み出し元の完全一致を確認し、平文の一時画像は削除済み。復元時は上記の復元例のバックアップ名と鍵名をこの組み合わせに置き換える。旧バックアップも保持している。

### Mac の Chrome 向け HID ブリッジ（プロトタイプ）

`mac-bridge/` と `tools/mac_ble_hid_bridge.py` は、Mac 内の仮想 FIDO HID と C3 の認証済み BLE リンクを中継する。BLE 準備後に HID を公開する。INIT / CBOR / PING / CANCEL / KEEPALIVE、チャンネル管理と分割を実装。秘密鍵はボード内で使用する。

macOS 26.5 で native ビルドとプロトコルテストを確認済み。ただし仮想 HID 作成は `com.apple.developer.hid.virtual.device` がないため実機で拒否された。Developer アカウントと開発証明書はあるが、現在のローカルプロファイルに当該権限はない。Chrome 認識・実サービスログインはまだ検証できていない。Apple の正式な権限付与と対応する macOS profile が必要。署名手順と申請文案は [mac-bridge/README.md](mac-bridge/README.md) を参照。
