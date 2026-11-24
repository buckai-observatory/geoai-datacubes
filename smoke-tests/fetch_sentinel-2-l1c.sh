#!/bin/bash
#SBATCH --job-name=geoai-smoke-fetch-sentinel-2-l1c
#SBATCH --time=00:15:00
#SBATCH --mem=4G
#SBATCH --cpus-per-task=2
#SBATCH --output=smoke-tests/logs/%x.%j.out
#SBATCH --error=smoke-tests/logs/%x.%j.err
# ---------------------------------------------------------------------------
# Smoke test: Sentinel-2 L1C top-of-atmosphere via Earth Search.
#
# Runs either as a regular bash script (local) or as a SLURM job:
#   bash   smoke-tests/fetch_sentinel-2-l1c.sh
#   sbatch smoke-tests/fetch_sentinel-2-l1c.sh
#
# Big outputs (the actual GeoTIFFs) land in $OUTDIR (default /tmp/geoai_smoke
# so they never accidentally land in git). A small JSON summary is written
# to smoke-tests/logs/fetch_sentinel-2-l1c.json so the run history can be committed.
# ---------------------------------------------------------------------------

# shellcheck source=_common.sh
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

# S2-L1C via Earth Search serves .jp2 assets. Rasterio/GDAL need the
# libgdal-jp2openjpeg driver to read them; that is now part of the
# recommended install recipe (docs/install.md + README). Microsoft
# Planetary Computer does not host L1C -- only L2A -- so the `auto`
# routing to earthsearch is the only free path. If the JP2 driver is
# missing, _run_fetch.py detects it and marks S2-L1C skipped rather
# than hard-failing.
python smoke-tests/_run_fetch.py "Sentinel-2-L1C"
