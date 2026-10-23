# diy-fido-key

市販の安い ESP32 ボードを `pico-fido` ファームウェアで焼いて作る、USB 接続の
FIDO2/WebAuthn パスキーデバイス（自作 YubiKey）。

出典: <https://www.makeuseof.com/made-own-yubikey-less-than-8/>

## 現在の状態（2026-10-23）

- **ESP32-S3 ボードで USB FIDO2 キーとして動作**。`GetInfo`（CTAP 2.3 / 1024 bytes）、登録（packed）、認証（署名 71B）、**再起動後の資格情報の永続化**を実機で確認
- 同じボードで **Flash Encryption (release) + Secure Boot v2 署名 (RSA-3072) + SDM** を有効化済み。以後の書き込みは **署名＋事前暗号化イメージ＋`--force`** が必要（[セキュリティプロファイル](#セキュリティプロファイルesp32-s3-の保護機能)）
- LCD にキャラクター画像と状態（READY / PRESS / WORKING）を表示
- ESP32-C3 の OLED / BLE(Zephyr) 版は**別系統の実験**として [docs/c3-ble.md](docs/c3-ble.md) に分離した（USB HID は不可）

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

このリポジトリでは Web ツールを使わず、**CLI でビルドして書き込む構成**も扱う（LCD 表示・
Flash Encryption を含む）。手順は「ESP32-S3 + ST7735 LCD」と「セキュリティプロファイル」を参照。
既に暗号化を有効にした個体では Web ツールでの書き込みはできない。

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

注意:

- `tools/install-esp32-lcd.sh` は LCD に加えて **`patches/pico-fido-psram-shadow.patch`**（`part0` を PSRAM のシャドウに載せる）も適用する。ビルドスクリプトは PSRAM（OCT / 40MHz / `IGNORE_NOTFOUND`）を有効にする
- 上の `write-flash` は **暗号化していない個体向け**。SDM（暗号化有効）の個体では失敗するので、[セキュリティプロファイル](#セキュリティプロファイルesp32-s3-の保護機能)の手順を使う

### LCD 設定（実機で確定）

- `MADCTL 0x08`（BGR）/ オフセット `col=26, row=1` / **INVON**
- 16bit カラーは **送信前にバイトスワップ必須**（ESP32 はリトルエンディアン、ST7735 は MSB first）。忘れると画像がモザイク状に崩れる
- SPI クロックは **12MHz** で動作確認（ST7735 の書き込み上限は概ね 15MHz。40MHz は未検証）
- ベンダーデモは TFT_eSPI の `TFT_eSPI(80,160)` + `setRotation(1)`。160x80 用の `GREENTAB160x80`（26,1 + INVON）に相当
- キャラ画像は `tools/make-lcd-image.py` で白背景を輪郭からフラッドフィルして透過し、`esp32-lcd/mascot_80x80.h` に埋め込む
- 校正用に `-DLCD_CALIBRATION=ON`（向き/オフセット/反転）と `-DLCD_COLOR_CAL=ON`（色順/バイト順）のビルドがある。BOOT 押下で候補を切り替える

### 実測結果（2026-10-22/23）

- `Pico Key`（VID:PID `2E8A:10FE`）として macOS に HID 列挙。CTAP 2.3 / max msg 1024
- `python-fido2` で登録（attestation `packed`、UP+AT）と認証（署名検証、counter 2、UP）に成功
- **Chrome からの WebAuthn も成功**（`tools/webauthn_local_test.py`、RP=`localhost:8787`）: `webauthn.create` → `webauthn.get`（署名 72 bytes、BOOT 承認）。サーバー側に challenge/credential を記録
- LCD にキャラ画像＋状態表示（READY / PRESS BOOT / WORKING）を出す `esp32-lcd/` を追加。色・向き・バイト順は実機で確定済み

### PIN（User Verification）

UV を要求するサービス（ChatGPT など）では PIN が必要。設定は対話式で、PIN は画面に出ない:

```sh
.venv/bin/python tools/set_fido_pin.py
```

### 落とし穴

- **USB-Serial/JTAG のセカンダリコンソールを有効にしたままだと、TinyUSB(OTG) と GPIO19/20 を奪い合い、TG0WDT の起動ループになる。** `CONFIG_ESP_CONSOLE_SECONDARY_NONE=y` にする（ビルドスクリプトが自動適用）
- フラッシュモードは **DIO** で動作確認（公式ビルドと同じ。QIO は未検証）
- 書き込み後に HID として動いている間は `/dev/cu.*` が消えるため、再書き込みは毎回 BOOT+挿し直しが必要
- Flash Encryption 有効後は **SDM** に入り、`read-flash` などの読み出しができない。書き込みは `--force` と事前暗号化イメージが必須で、**署名のないイメージは起動しない**

## ESP32-C3 / BLE 版

USB-OTG を持たない C3 での OLED 表示・Zephyr BLE FIDO2・ES256 鍵の取り込み・macOS 向け
BLE→HID ブリッジの試作は [docs/c3-ble.md](docs/c3-ble.md) に分離した。

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

`tools/security-profiles.sh` で保護レベルを切り替えます。**スクリプトは eFuse を焼きません**（ビルドと手順書のみ）。実機では下記の eFuse が既に焼かれています。

| プロファイル | Secure Boot | Flash Encryption | 用途 |
|---|---|---|---|
| `backup` | なし | なし | 開発・検証（再書き込み自由） |
| `encrypted` | RSA-3072 で署名（eFuse は焼かない） | development | 暗号化の試行 |
| `encrypted-release` | なし | release | 暗号化の試行用。**SDM では署名なしのため起動しない**（実測） |
| `secure` | RSA-3072（署名） | release | **実機で動作確認した構成** |

### 実機で確定した構成（2026-10-23）

- **ESP32-S3 の Secure Boot v2 は RSA-3072 のみ**（ECDSA は非対応）。ECDSA 鍵では起動時に署名検証で失敗する
- Flash Encryption を有効にすると **Secure Download Mode (SDM)** になる。SDM では `read-flash` / `chip-id` / eFuse 読み出しが不可で、**署名済みブートローダが必要**。書き込みは `--force` と事前暗号化イメージで行う
- pico-fido は `part0` を **mmap** するが、暗号化有効時は mmap が復号するため平文 FS と一致しない。`patches/pico-fido-psram-shadow.patch` で **PSRAM 上のシャドウ**に置き換え、`esp_flash_read/write`（平文）で読み書きする。`part0` は暗号化フラグを付けない
- PSRAM は **40MHz**、`CONFIG_SPIRAM_IGNORE_NOTFOUND=y`（未搭載でも起動）
- 署名付きブートローダは 32KB を超えるため、Secure Boot を含むプロファイルは **パーティションテーブルを 0x10000** に移動する（マージ済みイメージが配置を含む）。`encrypted-release` は 0x9000

### 鍵

- 署名鍵（RSA-3072）: `~/.config/diy-fido-key/secure-boot/secure-boot-rsa3072.pem`
- フラッシュ暗号化鍵: `~/.config/diy-fido-key/secure-boot/flash-encryption-key.bin`
- どちらも **オフラインで2箇所保管**。失うと更新不可

### 焼き方（SDM 有効後）

```sh
# ビルド（事前暗号化まで）
sh tools/security-profiles.sh secure
# 書き込み（SDM では --force、スタブなし）
esptool --port /dev/cu.usbmodemXXXX write-flash --force 0x0 build/pico-fido-secure/pico_fido_secure.enc.bin
```

書き込み後は BOOT を離して USB を挿し直す。`part0` のレイアウトを変えた場合だけ
`esptool --port ... erase-region 0x200000 0x100000` で保存領域を作り直す。

### 再書き込み不可にする（任意・一方通行）

「もう書き換えさせない」ための操作。**どれも戻せません**。完成したイメージで十分に
動作確認してから、最後に実施します。

| 操作 | 効果 | 戻せる |
|---|---|---|
| `SECURE_BOOT_EN` + digest | 署名済みイメージのみ起動（更新は署名鍵が必要） | ✗ |
| `DIS_DOWNLOAD_MODE` | ROM ダウンロードモードを無効化＝**再書き込み不可** | ✗ |
| `DIS_USB_JTAG` / `DIS_PAD_JTAG` | JTAG 経路を無効化 | ✗ |
| pico-fido Secure Lock | MKEK を OTP に固定（資格情報を端末に紐付け） | ✗ |

```sh
# 最後に実行する。事前に署名済みイメージでの起動確認と鍵の退避を済ませること
espefuse.py --port /dev/cu.usbmodemXXXX burn_efuse DIS_DOWNLOAD_MODE
espefuse.py --port /dev/cu.usbmodemXXXX burn_efuse DIS_USB_JTAG
```

注意:

- `DIS_DOWNLOAD_MODE` を焼くと **二度と書き込めない**（失敗時は基板ごと交換）
- 署名鍵・暗号化鍵の控えがない状態で焼かない
- 現行機は **未実施**（`DIS_DOWNLOAD_MODE` は未焼）なので、まだ更新できる
- 書き込み経路を残す限り、`SECURE_BOOT_EN` なしでも SDM + 暗号化で「読み出し不可・
  任意ファームの書き込み不可」までは達成できる（署名検証はされない）

### 実機で確認できたこと

- `GetInfo`（CTAP 2.3 / max 1024）、登録（packed / UP+AT）、認証（署名 71B / counter）、**再起動後の永続化**、LCD 表示
- eFuse 状態: `BLOCK_KEY0` に XTS 鍵、`SPI_BOOT_CRYPT_CNT = 0b001`、`SECURE_BOOT_EN` は未焼（署名は SDM 要求のため付与）
- 実機で実行した eFuse 操作（**一方通行**）:

```sh
espefuse.py --port /dev/cu.usbmodemXXXX burn_key BLOCK_KEY0 flash-encryption-key.bin XTS_AES_128_KEY
espefuse.py --port /dev/cu.usbmodemXXXX burn_efuse SPI_BOOT_CRYPT_CNT 0x1
```

## 参考リンク

- 紹介記事: <https://www.makeuseof.com/made-own-yubikey-less-than-8/>
- ファームウェア本体: <https://github.com/polhenarejos/pico-fido>
- Web 書き込みツール: <https://picokeys.com/esp32-flasher/>
