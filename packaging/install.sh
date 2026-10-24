#!/usr/bin/env sh
set -eu

here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

python=""
if [ -n "${FLYVIBING_PYTHON:-}" ]; then
    if "$FLYVIBING_PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
        python="$FLYVIBING_PYTHON"
    fi
else
    for candidate in python3 python; do
        if ! command -v "$candidate" >/dev/null 2>&1; then
            continue
        fi
        if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
            python="$candidate"
            break
        fi
    done
fi

if [ -z "$python" ]; then
    echo "ERROR: Python 3.10+ was not found." >&2
    echo "Install Python 3.10+ or set FLYVIBING_PYTHON to its executable." >&2
    exit 1
fi

echo "Using Python: $python"
exec "$python" "$here/install.py" "$@"
