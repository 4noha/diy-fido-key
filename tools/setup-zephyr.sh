#!/bin/sh
# SPDX-License-Identifier: Apache-2.0
set -eu
repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$repo_dir"
python3.13 -m venv .venv
.venv/bin/pip install -r tools/requirements.txt
mkdir -p vendor
if [ ! -d vendor/zephyr/.git ]; then
    git clone https://github.com/zephyrproject-rtos/zephyr.git vendor/zephyr
fi
git -C vendor/zephyr checkout ac03a4a9085d436d57cd2c5723f0616cfa709ab7
if [ ! -d vendor/.west ]; then
    .venv/bin/west init -l vendor/zephyr
fi
if [ ! -d vendor/u8g2/.git ]; then
    git clone https://github.com/olikraus/u8g2.git vendor/u8g2
fi
git -C vendor/u8g2 checkout 76b5646dd70058672ab37370a4e228a8347d8feb
.venv/bin/pip install -r vendor/zephyr/scripts/requirements-base.txt
cd vendor
../.venv/bin/west update hal_espressif mbedtls tf-psa-crypto zcbor
../.venv/bin/west blobs fetch hal_espressif
../.venv/bin/west sdk install --version 1.0.1 -b "$repo_dir/vendor/sdk" -t riscv64-zephyr-elf -H
