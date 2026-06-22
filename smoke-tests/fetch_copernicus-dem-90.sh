#!/bin/bash
#SBATCH --job-name=geoai-smoke-fetch-copernicus-dem-90
#SBATCH --time=00:10:00
#SBATCH --mem=2G
#SBATCH --cpus-per-task=2
#SBATCH --output=smoke-tests/logs/%x.%j.out
#SBATCH --error=smoke-tests/logs/%x.%j.err
# ---------------------------------------------------------------------------
# Smoke test: Copernicus DEM GLO-90 (90 m global, static)
# ---------------------------------------------------------------------------

# shellcheck source=_common.sh
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

python smoke-tests/_run_fetch.py "Copernicus-DEM-90"
