#!/bin/sh
# SPDX-License-Identifier: Apache-2.0
set -eu
repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
sh "$repo_dir/tools/apply-zephyr-patches.sh"
cd "$repo_dir/vendor"
../.venv/bin/west build -b esp32c3_devkitm -d ../build/zephyr ../zephyr-app "$@"
