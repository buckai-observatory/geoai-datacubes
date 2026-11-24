#!/bin/bash
#SBATCH --job-name=geoai-smoke-fetch-alos-dem
#SBATCH --time=00:10:00
#SBATCH --mem=2G
#SBATCH --cpus-per-task=2
#SBATCH --output=smoke-tests/logs/%x.%j.out
#SBATCH --error=smoke-tests/logs/%x.%j.err
# ---------------------------------------------------------------------------
# Smoke test: ALOS World 3D-30m DSM (AW3D30, static)
# ---------------------------------------------------------------------------

# shellcheck source=_common.sh
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

python smoke-tests/_run_fetch.py "ALOS-DEM"
