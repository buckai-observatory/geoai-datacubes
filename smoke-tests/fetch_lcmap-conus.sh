#!/bin/bash
#SBATCH --job-name=geoai-smoke-fetch-lcmap-conus
#SBATCH --time=00:10:00
#SBATCH --mem=2G
#SBATCH --cpus-per-task=2
#SBATCH --output=smoke-tests/logs/%x.%j.out
#SBATCH --error=smoke-tests/logs/%x.%j.err
# ---------------------------------------------------------------------------
# Smoke test: USGS LCMAP CONUS annual LULC (NLCD substitute, 30 m)
# ---------------------------------------------------------------------------

# shellcheck source=_common.sh
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

python smoke-tests/_run_fetch.py "LCMAP-CONUS"
