#!/bin/sh
set -eu

export PATH="$SNAP/usr/bin:$SNAP/bin:$PATH"
export PYTHONPATH="$SNAP/src:$SNAP/usr/lib/python3/dist-packages:$SNAP/lib/python3/dist-packages${PYTHONPATH:+:$PYTHONPATH}"

exec /usr/bin/python3 "$SNAP/src/main.py" "$@"
