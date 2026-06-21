#!/bin/bash
#SBATCH --job-name=geoai-smoke-pipeline-nan-auto
#SBATCH --time=00:05:00
#SBATCH --mem=2G
#SBATCH --cpus-per-task=2
#SBATCH --output=smoke-tests/logs/%x.%j.out
#SBATCH --error=smoke-tests/logs/%x.%j.err
# ---------------------------------------------------------------------------
# Smoke test: tile_geotiff(nan_handling="auto") on a synthetic 4-band cube.
#
# Validates the per-band-kind dispatch:
#   * spectral   -> fill_mean
#   * elevation  -> fill_biharmonic (or nearest fallback)
#   * categorical-> fill_nearest_int (output stays integer-valued)
#   * any > 10%  -> tile dropped regardless of kind
#
# No network. Runs in a couple of seconds. Runnable locally or under SLURM:
#   bash   smoke-tests/pipeline_nan_auto.sh
#   sbatch smoke-tests/pipeline_nan_auto.sh
# ---------------------------------------------------------------------------

# shellcheck source=_common.sh
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

python smoke-tests/_run_pipeline_nan_auto.py
