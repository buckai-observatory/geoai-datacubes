#!/bin/bash
#SBATCH --job-name=geoai-perf-bench
#SBATCH --time=01:00:00               # ~20-40 min typical; 1 h leaves margin
#SBATCH --mem=16G                     # rasterio warp on 400 km² @ 10 m fits
#SBATCH --cpus-per-task=4             # rasterio + threaded HTTP pool
#SBATCH --output=smoke-tests/perf_logs/%x.%j.out
#SBATCH --error=smoke-tests/perf_logs/%x.%j.err
# No --partition line -- inherits the site default. Override on the
# command line if your cluster needs a specific one:
#   sbatch --partition=<name> smoke-tests/perf_bench.slurm
# ---------------------------------------------------------------------------
# Benchmark fetch throughput across providers and AOI sizes.  Writes:
#   * <repo>/smoke-tests/perf_logs/geoai-perf-bench.<jobid>.out  (stdout)
#   * <repo>/smoke-tests/perf_logs/perf_bench_<label>_<ts>.jsonl (raw rows)
#   * <repo>/smoke-tests/perf_logs/                              (never pushed)
#
# The .jsonl and .out both stay local ([[feedback_geoai_local_tests]]);
# only the printed markdown table gets copy-pasted into docs/performance.qmd
# in the PR.
#
# Usage:
#   sbatch smoke-tests/perf_bench.slurm
#   sbatch --export=ALL,CONFIGS=quick smoke-tests/perf_bench.slurm
#   sbatch --export=ALL,LABEL=unity-a100  smoke-tests/perf_bench.slurm
#   sbatch --export=ALL,ENV_NAME=geoai-cubes smoke-tests/perf_bench.slurm
# ---------------------------------------------------------------------------
set -euo pipefail

if [ -n "${SLURM_SUBMIT_DIR:-}" ]; then
    REPO_ROOT="$SLURM_SUBMIT_DIR"
else
    REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fi
cd "$REPO_ROOT"
mkdir -p smoke-tests/perf_logs

# Activate the mamba/conda env that has geoai_datacubes installed.
# Override via --export=ALL,ENV_NAME=<name>; default 'geoai-cubes' matches
# the recommended mamba create line in docs/install.md.
ENV_NAME="${ENV_NAME:-geoai-cubes}"
for init in "$HOME"/mambaforge/etc/profile.d/conda.sh \
            "$HOME"/miniforge3/etc/profile.d/conda.sh \
            "$HOME"/anaconda3/etc/profile.d/conda.sh \
            /opt/anaconda3/etc/profile.d/conda.sh; do
    if [ -f "$init" ]; then
        # shellcheck disable=SC1090
        . "$init"
        break
    fi
done
# Prefer `conda activate` over `mamba activate` -- conda.sh above defines
# the `conda` shell function; `mamba activate` needs its own `mamba init`
# on top of that, which most SLURM shells don't have.
if command -v conda >/dev/null 2>&1; then
    conda activate "$ENV_NAME"
elif command -v mamba >/dev/null 2>&1; then
    mamba activate "$ENV_NAME"
else
    echo "!! neither conda nor mamba on PATH after conda-init sweep"
    echo "   activate '$ENV_NAME' yourself in your ~/.bashrc or job preamble"
    exit 2
fi

export PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}"

CONFIGS="${CONFIGS:-all}"
LABEL="${LABEL:-unity}"

echo "=========================================================================="
echo "geoai-datacubes: performance benchmark"
echo "  REPO_ROOT     : $REPO_ROOT"
echo "  SLURM_JOB     : ${SLURM_JOB_ID:-(local, not sbatch)}"
echo "  NODE          : $(hostname)"
echo "  ENV_NAME      : $ENV_NAME"
echo "  PYTHON        : $(command -v python)"
echo "  PACKAGE       : $(python -c 'import geoai_datacubes; print(geoai_datacubes.__file__)' 2>&1)"
echo "  CONFIGS PRESET: $CONFIGS"
echo "  LABEL         : $LABEL"
echo "=========================================================================="

# Load creds if present (falls back to whatever is already in the env)
if [ -f .env ]; then
    set -a; . ./.env; set +a
fi

python smoke-tests/perf_bench.py --configs "$CONFIGS" --label "$LABEL"

echo
echo "=========================================================================="
echo "Done.  Raw JSON log(s) in smoke-tests/perf_logs/ (local-only)."
echo "Copy the printed markdown table into docs/performance.qmd for the PR."
echo "=========================================================================="
