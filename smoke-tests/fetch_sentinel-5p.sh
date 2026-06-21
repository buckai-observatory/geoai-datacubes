#!/bin/bash
#SBATCH --job-name=geoai-smoke-fetch-sentinel-5p
#SBATCH --time=00:05:00
#SBATCH --mem=1G
#SBATCH --output=smoke-tests/logs/%x.%j.out
#SBATCH --error=smoke-tests/logs/%x.%j.err
# ---------------------------------------------------------------------------
# Smoke test: Sentinel-5P TROPOMI (documented STUB only).
#
# The Microsoft Planetary Computer Sentinel-5P collection serves NetCDF
# items, not Cloud-Optimised GeoTIFFs. Our fetcher only reads COGs via
# rasterio + /vsicurl/, so a real download cannot succeed here yet.
# _run_fetch.py recognises this and writes a 'skipped' log entry.
# ---------------------------------------------------------------------------

# shellcheck source=_common.sh
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

python smoke-tests/_run_fetch.py "Sentinel-5P"
