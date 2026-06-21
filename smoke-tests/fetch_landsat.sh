#!/bin/bash
#SBATCH --job-name=geoai-smoke-fetch-landsat
#SBATCH --time=00:15:00
#SBATCH --mem=4G
#SBATCH --cpus-per-task=2
#SBATCH --output=smoke-tests/logs/%x.%j.out
#SBATCH --error=smoke-tests/logs/%x.%j.err
# ---------------------------------------------------------------------------
# Smoke test: Landsat 8/9 Collection 2 L2 via Planetary Computer.
#
# Runs either as a regular bash script (local) or as a SLURM job:
#   bash   smoke-tests/fetch_landsat.sh
#   sbatch smoke-tests/fetch_landsat.sh
#
# Big outputs (the actual GeoTIFFs) land in $OUTDIR (default /tmp/geoai_smoke
# so they never accidentally land in git). A small JSON summary is written
# to smoke-tests/logs/fetch_landsat.json so the run history can be committed.
# ---------------------------------------------------------------------------

# shellcheck source=_common.sh
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

python smoke-tests/_run_fetch.py "Landsat"
