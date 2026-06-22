#!/bin/bash
#SBATCH --job-name=geoai-smoke-fetch-alos-fnf
#SBATCH --time=00:10:00
#SBATCH --mem=2G
#SBATCH --cpus-per-task=2
#SBATCH --output=smoke-tests/logs/%x.%j.out
#SBATCH --error=smoke-tests/logs/%x.%j.err
# ---------------------------------------------------------------------------
# Smoke test: JAXA ALOS Forest / Non-Forest annual mosaic via PC.
# 25 m global categorical map (dense forest / non-dense forest / non-forest
# / water) derived from PALSAR L-band SAR. Useful as a forest-cover label
# at a coarser resolution than ESA WorldCover but with annual updates.
#
# Runs as plain bash or under SLURM:
#   bash   smoke-tests/fetch_alos-fnf.sh
#   sbatch smoke-tests/fetch_alos-fnf.sh
# ---------------------------------------------------------------------------

# shellcheck source=_common.sh
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

python smoke-tests/_run_fetch.py "ALOS-FNF"
