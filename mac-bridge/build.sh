#!/bin/sh
set -eu
repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
mkdir -p "$repo_dir/build/mac-bridge"
xcrun clang -mmacosx-version-min=12.0 -fobjc-arc -fblocks -Wall -Wextra -Wno-unused-parameter \
    -framework Foundation -framework IOKit \
    "$repo_dir/mac-bridge/hid_host.m" -o "$repo_dir/build/mac-bridge/hid_host"
