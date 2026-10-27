#!/usr/bin/env bash
# Run Veriq on every example and print a summary table.
# Exits non-zero if any example gets a verdict other than the one it should get.
set -u
cd "$(dirname "$0")/.."
VERIQ="${VERIQ:-veriq}"
if ! command -v "$VERIQ" >/dev/null 2>&1; then
  if [ -x .venv/bin/veriq ]; then VERIQ=.venv/bin/veriq; else VERIQ="python -m veriq"; fi
fi
OUT=reports
mkdir -p "$OUT"
E=examples

# name | expected verdict | args
CASES=(
  "bell_correct|PASS|$E/bell_correct.py --expect $E/expect/bell.json"
  "bell_qasm2|PASS|$E/bell.qasm --expect $E/expect/bell.json --backend generic"
  "ghz_correct|PASS|$E/ghz_correct.py --expect $E/expect/ghz3.json --backend generic"
  "ghz_qasm3|PASS|$E/ghz3.qasm3 --reference $E/ghz_correct.py"
  "ghz_buggy|FAIL|$E/ghz_buggy.py --reference $E/ghz_correct.py --expect $E/expect/ghz3.json"
  "qft_correct|PASS|$E/qft_correct.py --reference $E/qft_reference.py"
  "qft_buggy|FAIL|$E/qft_buggy.py --reference $E/qft_reference.py"
  "grover_correct|PASS|$E/grover_correct.py --reference $E/grover_reference.py --expect $E/expect/grover3_101.json"
  "grover_buggy|FAIL|$E/grover_buggy.py --reference $E/grover_reference.py --expect $E/expect/grover3_101.json"
)

bad=0
rows=()
for c in "${CASES[@]}"; do
  IFS='|' read -r name want args <<<"$c"
  echo "=== $name (expected $want)"
  start=$(date +%s.%N)
  # shellcheck disable=SC2086
  $VERIQ check $args --report "$OUT/$name.html"
  end=$(date +%s.%N)
  got=$(python3 -c "import json;print(json.load(open('$OUT/$name.json'))['verdict'])" 2>/dev/null || echo ERROR)
  ok="ok"; [ "$got" = "$want" ] || { ok="MISMATCH"; bad=1; }
  rows+=("$(printf '%-16s %-8s %-13s %6.2fs  %s' "$name" "$want" "$got" "$(awk "BEGIN{print $end - $start}")" "$ok")")
  echo
done

echo "================ Veriq demo summary ================"
printf '%-16s %-8s %-13s %7s  %s\n' example expected verdict time status
for r in "${rows[@]}"; do echo "$r"; done
echo "reports in $OUT/"
exit $bad
