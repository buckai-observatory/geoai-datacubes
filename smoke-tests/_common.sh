# Shared boilerplate for every smoke-test script.
#
# Sourced (not executed) by each fetch_*.sh / pipeline_*.sh. Sets up
# OUTDIR / LOGDIR / REPO and a trap that writes a status JSON if the
# Python step fails before _run_fetch.py gets a chance to.
#
# A note on SLURM-vs-bash: every smoke-test script in this folder is a
# valid bash script AND a valid SLURM job script -- the `#SBATCH` lines
# at the top are comments to bash but directives to sbatch. So:
#
#   bash  smoke-tests/fetch_sentinel-2.sh        # local
#   sbatch smoke-tests/fetch_sentinel-2.sh        # cluster
#
# both work. The SLURM headers default to modest resource asks; override
# with `sbatch --mem=8G --time=00:30:00 ...` if you need more.

# Bail on any error, undefined variable, or pipe failure.
set -euo pipefail

# Resolve the repo root regardless of where the script is invoked from
# (relative path from bash, $SLURM_SUBMIT_DIR from sbatch).
THIS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$THIS_DIR/.." && pwd)"
cd "$REPO_ROOT"

# Big outputs go to OUTDIR (default outside the repo so they never land
# in git by accident). Logs (small JSON summaries) go inside the repo
# under smoke-tests/logs/ so the test history can be committed.
export OUTDIR="${OUTDIR:-/tmp/geoai_smoke}"
export LOGDIR="$REPO_ROOT/smoke-tests/logs"
mkdir -p "$OUTDIR" "$LOGDIR"

# Make `import geoai_datacubes` work without requiring `pip install -e .`
# first. A contributor who *has* installed the package will see the same
# import path; pip resolution still prefers the installed copy when both
# are present.
export PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}"

# Per-script id (filename without extension). Used for the log JSON
# path and a leading banner.
SCRIPT_NAME="$(basename "${BASH_SOURCE[1]:-$0}" .sh)"
export SCRIPT_NAME

echo "=========================================================================="
echo "smoke-test: $SCRIPT_NAME"
echo "  REPO_ROOT  : $REPO_ROOT"
echo "  OUTDIR     : $OUTDIR"
echo "  LOGDIR     : $LOGDIR"
echo "  PYTHON     : $(command -v python || echo MISSING)"
echo "  SLURM_JOB  : ${SLURM_JOB_ID:-(not running under sbatch)}"
echo "=========================================================================="

# Fallback log entry written if Python crashes hard before writing its
# own. _run_fetch.py overwrites this with the real result on success.
LOG_JSON="$LOGDIR/$SCRIPT_NAME.json"
python - "$SCRIPT_NAME" "$LOG_JSON" <<'PY'
import json, sys, datetime
name, path = sys.argv[1], sys.argv[2]
with open(path, "w") as f:
    json.dump({
        "test": name,
        "status": "running",
        "started_at": datetime.datetime.now().isoformat(timespec="seconds"),
    }, f, indent=2)
PY
