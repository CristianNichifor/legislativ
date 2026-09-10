#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
python_bin="${LEGISLATIV_PYTHON:-python3}"
if ! "$python_bin" -c 'import sys; sys.exit(sys.version_info < (3, 12))' 2>/dev/null; then
  echo "Instaleaza Python 3.12+ (python.org), apoi ruleaza din nou. Python nu este inclus."
  exit 1
fi
if [[ -f legislativ.pyz ]]; then
  exec "$python_bin" -B legislativ.pyz "$@"
fi
exec "$python_bin" -B -m scripts.launcher "$@"
