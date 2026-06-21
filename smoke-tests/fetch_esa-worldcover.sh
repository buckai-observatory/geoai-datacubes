#!/bin/bash
#SBATCH --job-name=geoai-smoke-fetch-esa-worldcover
#SBATCH --time=00:10:00
#SBATCH --mem=2G
#SBATCH --cpus-per-task=2
#SBATCH --output=smoke-tests/logs/%x.%j.out
#SBATCH --error=smoke-tests/logs/%x.%j.err
# ---------------------------------------------------------------------------
# Smoke test: ESA WorldCover 10 m LULC via PC (static).
#
# Runs either as a regular bash script (local) or as a SLURM job:
#   bash   smoke-tests/fetch_esa-worldcover.sh
#   sbatch smoke-tests/fetch_esa-worldcover.sh
#
# Big outputs (the actual GeoTIFFs) land in $OUTDIR (default /tmp/geoai_smoke
# so they never accidentally land in git). A small JSON summary is written
# to smoke-tests/logs/fetch_esa-worldcover.json so the run history can be committed.
# ---------------------------------------------------------------------------

# shellcheck source=_common.sh
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

python smoke-tests/_run_fetch.py "ESA-WorldCover"
