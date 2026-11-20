#!/bin/bash
# Каждый tests/*_test.py отдельным процессом, offscreen, временные HOME и XDG_*; итог по файлам.
# Запуск: bash tools/run_tests.sh [шаблон]   (по умолчанию все)
cd "$(dirname "$0")/.."
PY=${PY:-$HOME/.local/share/clipshot-venv/bin/python}
REALHOME=$HOME
fail=0
for t in tests/${1:-*}_test.py; do
  tmp=$(mktemp -d "${TMPDIR:-/tmp}/clipsd-t-XXXX")
  mkdir -p "$tmp/cfg" "$tmp/cache" "$tmp/data" "$tmp/run"; chmod 700 "$tmp/run"
  out=$(cd "$PWD" && HOME=$tmp XDG_CONFIG_HOME=$tmp/cfg XDG_CACHE_HOME=$tmp/cache XDG_DATA_HOME=$tmp/data \
        XDG_RUNTIME_DIR=$tmp/run QT_QPA_PLATFORM=${QT_QPA_PLATFORM:-offscreen} CLIPSD_LANG=${CLIPSD_LANG:-ru} \
        timeout 600 "$PY" "$t" 2>&1)
  rc=$?
  rm -rf "$tmp"   # своя временная папка теста (1.32.3: раньше оставалась после каждого прогона)
  if [ $rc -eq 0 ]; then echo "OK   $t"; else echo "FAIL $t (rc=$rc)"; echo "$out" | tail -15 | sed 's/^/     /'; fail=1; fi
done
exit $fail
