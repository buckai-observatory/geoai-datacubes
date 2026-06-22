#!/bin/bash
#SBATCH --job-name=geoai-smoke-fetch-hansen-gfc
#SBATCH --time=00:15:00
#SBATCH --mem=4G
#SBATCH --cpus-per-task=2
#SBATCH --output=smoke-tests/logs/%x.%j.out
#SBATCH --error=smoke-tests/logs/%x.%j.err
# ---------------------------------------------------------------------------
# Smoke test: Hansen Global Forest Change v1.11 via direct HTTP (no STAC).
# 30 m global tree-cover baseline + annual forest-loss raster. First mission
# wired through the new `direct_http` provider class.
#
# Runs as plain bash or under SLURM:
#   bash   smoke-tests/fetch_hansen-gfc.sh
#   sbatch smoke-tests/fetch_hansen-gfc.sh
# ---------------------------------------------------------------------------

# shellcheck source=_common.sh
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

python smoke-tests/_run_fetch.py "Hansen-GFC"
