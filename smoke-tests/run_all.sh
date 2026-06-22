#!/bin/bash
#SBATCH --job-name=geoai-smoke-run-all
#SBATCH --time=02:00:00
#SBATCH --mem=4G
#SBATCH --cpus-per-task=2
#SBATCH --output=smoke-tests/logs/%x.%j.out
#SBATCH --error=smoke-tests/logs/%x.%j.err
# ---------------------------------------------------------------------------
# Run every smoke test in this folder in sequence and print a summary table.
#
#   bash   smoke-tests/run_all.sh                # local, one after another
#   sbatch smoke-tests/run_all.sh                # single SLURM job, sequential
#
# To run them all as INDEPENDENT SLURM jobs (so they overlap):
#   for s in smoke-tests/fetch_*.sh smoke-tests/pipeline_*.sh; do
#       sbatch "$s"
#   done
#
# The per-test JSON logs land in smoke-tests/logs/<test>.json; this
# wrapper reads them back at the end to build a passed/failed/skipped
# summary and writes smoke-tests/logs/run_all.json with the same data.
# ---------------------------------------------------------------------------

set -uo pipefail

# Locate the repo and reuse the same env setup the per-test scripts use.
THIS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$THIS_DIR/.." && pwd)"
cd "$REPO_ROOT"

export OUTDIR="${OUTDIR:-/tmp/geoai_smoke}"
export LOGDIR="$REPO_ROOT/smoke-tests/logs"
export PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}"
mkdir -p "$OUTDIR" "$LOGDIR"

# Default order: pipeline tests first (fast + no network) so a broken
# install fails loudly before we spend bandwidth on STAC fetches.
TESTS=(
    smoke-tests/pipeline_nan_auto.sh
    smoke-tests/fetch_copernicus-dem.sh
    smoke-tests/fetch_esa-worldcover.sh
    smoke-tests/fetch_jrc-gsw.sh
    smoke-tests/fetch_3dep.sh
    smoke-tests/fetch_naip.sh
    smoke-tests/fetch_sentinel-2.sh
    smoke-tests/fetch_sentinel-2-l1c.sh
    smoke-tests/fetch_sentinel-1.sh
    smoke-tests/fetch_landsat.sh
    smoke-tests/fetch_modis-sr.sh
    smoke-tests/fetch_modis-lst.sh
    smoke-tests/fetch_hls-s30.sh
    smoke-tests/fetch_hls-l30.sh
    smoke-tests/fetch_planetscope-4b.sh
    smoke-tests/fetch_planetscope-8b.sh
    smoke-tests/fetch_alos-palsar.sh
    smoke-tests/fetch_alos-fnf.sh
    smoke-tests/fetch_hansen-gfc.sh
    smoke-tests/fetch_sentinel-5p.sh
)

START_TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "=========================================================================="
echo "geoai-datacubes smoke-tests :: run_all"
echo "  started_at : $START_TS"
echo "  TESTS      : ${#TESTS[@]}"
echo "  OUTDIR     : $OUTDIR"
echo "  LOGDIR     : $LOGDIR"
echo "=========================================================================="

# Run each test. We do NOT stop on first failure -- the point of run_all
# is to surface every breakage at once.
for t in "${TESTS[@]}"; do
    echo
    echo "--------------------------------------------------------------------------"
    echo ">>> $t"
    echo "--------------------------------------------------------------------------"
    bash "$t" || echo "  (exit=$? -- continuing to next test)"
done

# Aggregate the JSON logs back into a single summary. Python handles
# the missing-log / partial-write cases cleanly.
echo
echo "=========================================================================="
echo "SUMMARY"
echo "=========================================================================="
python - <<PY
import json, datetime
from pathlib import Path

logdir = Path("$LOGDIR")
tests  = [Path(t).stem for t in """$(printf "%s\n" "${TESTS[@]}")""".strip().splitlines()]

rows = []
for name in tests:
    p = logdir / f"{name}.json"
    if not p.exists():
        rows.append({"test": name, "status": "missing", "elapsed_sec": None})
        continue
    try:
        rec = json.loads(p.read_text())
    except Exception as e:
        rows.append({"test": name, "status": f"unreadable:{e}", "elapsed_sec": None})
        continue
    rows.append({
        "test": name,
        "status": rec.get("status", "?"),
        "elapsed_sec": rec.get("elapsed_sec"),
        "reason": rec.get("reason"),
        "error":  rec.get("error"),
    })

# Pretty table to stdout
print(f"{'test':40s}  {'status':9s}  {'elapsed':>8s}  notes")
print("-" * 80)
for r in rows:
    e = "" if r["elapsed_sec"] is None else f"{r['elapsed_sec']:.1f}s"
    note = r.get("error") or r.get("reason") or ""
    if len(note) > 60:
        note = note[:57] + "..."
    print(f"{r['test']:40s}  {r['status']:9s}  {e:>8s}  {note}")

# Tallies
from collections import Counter
tally = Counter(r["status"] for r in rows)
total = len(rows)
print("-" * 80)
print(f"total={total}  " + "  ".join(f"{k}={v}" for k, v in sorted(tally.items())))

# Combined JSON log for git diffing
out = {
    "started_at":  "$START_TS",
    "finished_at": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
    "tests": rows,
    "tally": dict(tally),
    "total": total,
}
(logdir / "run_all.json").write_text(json.dumps(out, indent=2))
print(f"\nWritten: {logdir / 'run_all.json'}")

# Exit non-zero if any test failed (skipped / missing are OK)
import sys
fail_states = {"failed", "missing"}
if any(r["status"].startswith("unreadable") or r["status"] in fail_states for r in rows):
    sys.exit(1)
PY
