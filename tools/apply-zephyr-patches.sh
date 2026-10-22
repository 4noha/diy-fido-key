#!/bin/sh
set -eu
repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
patch_file="$repo_dir/patches/zephyr-imported-credential-ids.patch"
if git -C "$repo_dir/vendor/zephyr" apply --check "$patch_file" 2>/dev/null; then
    git -C "$repo_dir/vendor/zephyr" apply "$patch_file"
elif ! git -C "$repo_dir/vendor/zephyr" apply --reverse --check "$patch_file" 2>/dev/null; then
    echo 'Zephyr import patch does not match the checkout; refusing to build.' >&2
    exit 1
fi
