#!/usr/bin/env bash
# Enclave terminal entry point: finds the project's Python and runs tools/enclave.py.
#   bash tools/enclave.sh help                        # from the repo root     # commands; guide: docs/enclave_terminal.md
# Python: SANDBOX_PYTHON if given. Otherwise, in order, .venv/bin/python (only if present locally), python3.11,
# python3.12, python3.13, python3.10, python3, python: the first that fits requirements.txt (>= 3.10, pandas >= 2);
# if none fits, the first with pandas, else the first >= 3.10 (req R5 shows what is missing).
set -u
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)" || exit 1
cd "$root" || exit 1

py="${SANDBOX_PYTHON:-}"
if [ -z "$py" ]; then
  any=""; with_pandas=""
  for c in "$root/.venv/bin/python" python3.11 python3.12 python3.13 python3.10 python3 python; do
    command -v "$c" >/dev/null 2>&1 || continue
    "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1 || continue
    [ -z "$any" ] && any="$c"
    "$c" -c 'import pandas' >/dev/null 2>&1 || continue
    [ -z "$with_pandas" ] && with_pandas="$c"
    if "$c" -c 'import sys, pandas; sys.exit(0 if int(pandas.__version__.split(".")[0]) >= 2 else 1)' >/dev/null 2>&1; then
      py="$c"; break
    fi
  done
  py="${py:-${with_pandas:-$any}}"
fi
if [ -z "$py" ]; then
  echo "Python >= 3.10 not found (tried: python3.11 python3.12 python3.13 python3.10 python3 python)."
  echo "Point to the Python DHA installed:  SANDBOX_PYTHON=/full/path/python3 bash $root/tools/enclave.sh $*"
  exit 1
fi
exec "$py" tools/enclave.py "$@"
