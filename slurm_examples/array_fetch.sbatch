#!/bin/bash
# ---------------------------------------------------------------------------
# array_fetch.sbatch -- fetch many (mission, time_range) combinations in
# parallel using a SLURM job array.
# ---------------------------------------------------------------------------
# A SLURM "job array" launches N copies of the same script with a different
# ${SLURM_ARRAY_TASK_ID} in each copy. That's the easy way to parallelise
# embarrassingly-parallel work like fetching different scenes / dates /
# missions for the same AOI.
#
# This template:
#   * defines an in-script TASKS array of (MISSION, START, END) tuples;
#   * uses ${SLURM_ARRAY_TASK_ID} to pick one tuple per array task;
#   * invokes a tiny inline Python driver that calls fetch_sentinel_data()
#     directly so we don't have to mutate main.py for every task.
#
# Submit with:   sbatch array_fetch.sbatch
# (The "--array" in the header below decides how many tasks run.)
# ---------------------------------------------------------------------------

#SBATCH --job-name=geoai-array
#SBATCH --output=logs/%x_%A_%a.out         # %A=array job id, %a=task id
#SBATCH --error=logs/%x_%A_%a.err

# ---- Array shape ----------------------------------------------------------
# Tasks are 0-indexed. Adjust this range to match the size of the TASKS list
# below. "%4" caps simultaneous tasks at 4 (good citizen on shared clusters);
# remove it to let the scheduler run all tasks at once.
#SBATCH --array=0-5%4

# ---- Per-task resources ---------------------------------------------------
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=00:30:00

# ---- CLUSTER-SPECIFIC PLACEHOLDERS ----------------------------------------
#SBATCH --account=YOUR_ALLOCATION
#SBATCH --partition=YOUR_PARTITION
#SBATCH --mail-user=YOUR_EMAIL@example.edu
#SBATCH --mail-type=END,FAIL

mkdir -p "${SLURM_SUBMIT_DIR}/logs"

# ---------------------------------------------------------------------------
# Environment activation (edit for your cluster -- see the BuckAI HPC Handbook).
# ---------------------------------------------------------------------------
# module purge
# module load miniconda3
source activate geoai-datacubes

cd "${SLURM_SUBMIT_DIR}/modules/sentinel_pipeline"

# ---------------------------------------------------------------------------
# Task table. One row per array task. Add / remove rows and update --array=
# above to match.
#
# Columns: MISSION  START_DATE  END_DATE
# ---------------------------------------------------------------------------
TASKS=(
    "Sentinel-2     2024-06-01  2024-06-30"
    "Sentinel-2     2024-07-01  2024-07-31"
    "Sentinel-2     2024-08-01  2024-08-31"
    "Sentinel-1     2024-06-01  2024-06-30"
    "Landsat        2024-06-01  2024-09-30"
    "Copernicus-DEM 2020-01-01  2020-12-31"
)

# Pick this task's row.
TASK="${TASKS[${SLURM_ARRAY_TASK_ID}]}"
read -r MISSION START END <<< "${TASK}"
echo "[$(date '+%F %T')] task ${SLURM_ARRAY_TASK_ID}: ${MISSION} ${START}..${END}"

# ---------------------------------------------------------------------------
# Tiny inline driver. Calls fetch_sentinel_data() directly so we can vary
# mission + time_range per task without editing main.py. Edit the AOI block
# below for your area of interest -- the four supported AOI formats are
# documented in modules/sentinel_pipeline/aoi.py.
# ---------------------------------------------------------------------------
python - <<PY
import os, sys, time
sys.path.insert(0, ".")
from aoi import resolve_aoi
from fetch_data import fetch_sentinel_data

# ---- EDIT ME -------------------------------------------------------------
AOI         = {"bbox": [-83.077, 39.964, -82.983, 40.036]}   # OSU ~5 mi sq.
RESOLUTION  = 10
MAX_CLOUD   = 0.20
SAVE_FOLDER = os.path.join(os.environ.get("SLURM_SUBMIT_DIR", "."), "data")
# --------------------------------------------------------------------------

ROI = resolve_aoi(AOI)
t0  = time.time()
data, bands = fetch_sentinel_data(
    mission="${MISSION}",
    bands=None,                           # mission defaults
    time_range=("${START}", "${END}"),
    roi=ROI,
    resolution=RESOLUTION,
    save_folder=SAVE_FOLDER,
    max_cloud_coverage=MAX_CLOUD,
    provider="auto",
)
print(f"OK: {{'mission':'${MISSION}','bands':{bands},'elapsed_s':{time.time()-t0:.1f}}}")
PY

echo "[$(date '+%F %T')] task ${SLURM_ARRAY_TASK_ID} done."
