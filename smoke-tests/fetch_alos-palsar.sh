#!/bin/bash
#SBATCH --job-name=geoai-smoke-fetch-alos-palsar
#SBATCH --time=00:15:00
#SBATCH --mem=4G
#SBATCH --cpus-per-task=2
#SBATCH --output=smoke-tests/logs/%x.%j.out
#SBATCH --error=smoke-tests/logs/%x.%j.err
# ---------------------------------------------------------------------------
# Smoke test: JAXA ALOS PALSAR annual L-band SAR mosaic via PC.
# 25 m HH/HV backscatter; standard input for global forest-biomass studies
# because L-band penetrates dry canopies further than Sentinel-1 C-band.
#
# Runs as plain bash or under SLURM:
#   bash   smoke-tests/fetch_alos-palsar.sh
#   sbatch smoke-tests/fetch_alos-palsar.sh
# ---------------------------------------------------------------------------

# shellcheck source=_common.sh
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

python smoke-tests/_run_fetch.py "ALOS-PALSAR"
