#!/bin/bash
#SBATCH --job-name=geoai-check-env
#SBATCH --time=00:05:00
#SBATCH --mem=1G
#SBATCH --cpus-per-task=1
#SBATCH --output=smoke-tests/logs/%x.%j.out
#SBATCH --error=smoke-tests/logs/%x.%j.err
# ---------------------------------------------------------------------------
# Verify the currently-active Python env satisfies requirements.txt.
#
# Two modes:
#   1) Default (fast, no network): import every package and report missing.
#   2) --pip            (slower, version-aware): `pip install --dry-run` runs
#      pip's resolver against requirements.txt; lines starting "Would install"
#      are the deltas you'd need to install.
#
# Usage:
#   bash smoke-tests/check_env.sh                # fast import check
#   bash smoke-tests/check_env.sh --pip          # pip dry-run
#   sbatch smoke-tests/check_env.sh              # run as a SLURM job (rare)
#
# Exit codes:
#   0  every package importable (or --pip says nothing to install)
#   1  at least one missing package
# ---------------------------------------------------------------------------
set -uo pipefail

THIS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$THIS_DIR/.." && pwd)"
cd "$REPO_ROOT"

MODE="${1:-import}"

# Map requirements.txt names to their importable Python module names where
# they differ (most don't). Single source of truth so we don't drift.
PKG_TO_IMPORT="
requests:requests
rasterio:rasterio
numpy:numpy
matplotlib:matplotlib
tqdm:tqdm
zarr:zarr
lmdb:lmdb
pystac:pystac
pandas:pandas
torch:torch
torchvision:torchvision
pillow:PIL
scikit-learn:sklearn
xgboost:xgboost
joblib:joblib
threadpoolctl:threadpoolctl
ultralytics:ultralytics
transformers:transformers
huggingface_hub:huggingface_hub
seaborn:seaborn
python-dotenv:dotenv
sentinelhub:sentinelhub
geopandas:geopandas
contextily:contextily
"

case "$MODE" in
  --pip|-p)
    echo "[check_env] pip dry-run against requirements.txt"
    echo "(lines starting 'Would install' = missing from your env;"
    echo " 'Requirement already satisfied' = OK)"
    echo
    # No --quiet -- the 'already satisfied' lines are the proof
    # everything is OK. Without them, empty output is ambiguous.
    LOG=$(mktemp)
    python -m pip install --dry-run -r requirements.txt > "$LOG" 2>&1 || true
    grep -E "Would install|Requirement already satisfied|ERROR" "$LOG" | head -80
    echo
    echo "[check_env] summary:"
    awk '
        /Would install/                  { miss++ ; print "  MISS  " substr($0, index($0, "Would install")) }
        /Requirement already satisfied/  { ok++ }
        END                              { print "  total OK   = " (ok ? ok : 0)
                                           print "  total MISS = " (miss ? miss : 0) }
    ' "$LOG"
    rm -f "$LOG"
    ;;
  import|--import|-i)
    echo "[check_env] import check (fast, no network)"
    echo
    python - <<PY
import importlib, sys
mapping = """${PKG_TO_IMPORT}"""
missing = []
for line in mapping.strip().splitlines():
    pkg, mod = line.split(":", 1)
    try:
        importlib.import_module(mod)
        print(f"  OK    {pkg:25s}  ({mod})")
    except Exception as e:
        missing.append((pkg, mod, str(e).splitlines()[0]))
        print(f"  MISS  {pkg:25s}  ({mod})  -- {str(e).splitlines()[0][:60]}")

print()
print(f"missing: {len(missing)}")
if missing:
    print()
    print("Install the missing ones with:")
    print("  mamba install -y -c conda-forge \\\\")
    print("     " + " ".join(p for p, _, _ in missing))
    print("  # or:")
    print("  pip install " + " ".join(p for p, _, _ in missing))
sys.exit(0 if not missing else 1)
PY
    ;;
  *)
    echo "Usage: $0 [--pip|--import]"
    exit 2
    ;;
esac
