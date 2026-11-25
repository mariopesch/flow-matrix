#!/usr/bin/env bash
# Start LED Animator with the settings from config.env (written by install.sh).
# Extra arguments are passed to app.py, e.g.  ./run.sh --brightness 30
set -e
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# The matrix needs root for GPIO timing
if [ "$EUID" -ne 0 ]; then
    exec sudo "$0" "$@"
fi

# shellcheck disable=SC1091
[ -f "$DIR/config.env" ] && . "$DIR/config.env"

PYTHON="$DIR/venv/bin/python"
if [ ! -x "$PYTHON" ]; then
    echo "No virtual environment found in $DIR/venv - run ./install.sh first." >&2
    exit 1
fi

cd "$DIR"
# shellcheck disable=SC2086  # EXTRA_ARGS is intentionally word-split
exec "$PYTHON" app.py \
    --port "${PORT:-8080}" \
    --chain "${CHAIN:-3}" \
    --mapping "${MAPPING:-adafruit-hat}" \
    --slowdown "${SLOWDOWN:-2}" \
    ${EXTRA_ARGS:-} "$@"
