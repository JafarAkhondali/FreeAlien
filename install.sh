#!/bin/sh
set -eu
source_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python3 "$source_dir/packaging/setup.py" "$@"
