#!/bin/sh
# One-time service installation. Runtime operations do not use sudo or pkexec.
set -eu
source_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec /usr/bin/python3 -I "$source_dir/install_thermals.py" "$@"
