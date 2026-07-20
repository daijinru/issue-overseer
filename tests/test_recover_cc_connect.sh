#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "$0")/.." && pwd)"
script="$script_dir/recover-cc-connect.sh"

test -x "$script"
bash -n "$script"
"$script" --help | grep -Fq '恢复本机 cc-connect Bridge'
