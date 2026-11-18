#!/usr/bin/env bash
# Enclave terminal girişi: projenin Python'unu bulur ve tools/enclave.py'yi çalıştırır.
#   bash tools/enclave.sh help                        # repo kökünden          # komutlar; rehber: docs/enclave_terminal.md
# Python: SANDBOX_PYTHON verilmişse o. Yoksa sırayla .venv/bin/python (yalnız yerelde varsa), python3.11,
# python3.12, python3.13, python3.10, python3, python içinden requirements.txt'e uyan (>= 3.10, pandas >= 2) ilki;
# uyan yoksa pandas'lı ilki, o da yoksa >= 3.10 ilki (req R5 eksiği gösterir).
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
  echo "Python >= 3.10 bulunamadı (denenen: python3.11 python3.12 python3.13 python3.10 python3 python)."
  echo "DHA'nın kurduğu Python'u ver:  SANDBOX_PYTHON=/tam/yol/python3 bash $root/tools/enclave.sh $*"
  exit 1
fi
exec "$py" tools/enclave.py "$@"
