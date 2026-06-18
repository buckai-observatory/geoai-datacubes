#!/bin/bash
# ---------------------------------------------------------------------------
# single_fetch.sbatch -- run one geoai-datacubes fetch on a SLURM cluster
# ---------------------------------------------------------------------------
# A minimal, GENERIC SLURM batch script. Fill in the placeholders below for
# your cluster (allocation/account, partition/queue, your e-mail). Cluster-
# specific guidance (which partition names exist, which modules to load, how
# to activate conda, etc.) lives in the BuckAI HPC Handbook -- ask the
# Observatory team for the URL or local path.
#
# Submit with:    sbatch single_fetch.sbatch
# Check status:   squeue -u $USER
# Cancel a job:   scancel <jobid>
# ---------------------------------------------------------------------------

#SBATCH --job-name=geoai-fetch
#SBATCH --output=logs/%x_%j.out            # %x = job name, %j = job id
#SBATCH --error=logs/%x_%j.err

# ---- Resources ------------------------------------------------------------
# A single fetch is mostly network-bound + a little CPU for resampling.
# 1 CPU and a few GB of RAM are usually enough for a city-scale AOI. Scale
# memory up if your AOI is large (e.g. an entire MGRS tile = ~100x100 km).
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=00:30:00                    # walltime: HH:MM:SS

# ---- CLUSTER-SPECIFIC PLACEHOLDERS ----------------------------------------
# Replace these with the values your sysadmin gave you.
#SBATCH --account=YOUR_ALLOCATION
#SBATCH --partition=YOUR_PARTITION
#SBATCH --mail-user=YOUR_EMAIL@example.edu
#SBATCH --mail-type=END,FAIL

# ---------------------------------------------------------------------------
# Make sure the logs/ folder exists relative to the submit directory.
# ---------------------------------------------------------------------------
mkdir -p "${SLURM_SUBMIT_DIR}/logs"

# ---------------------------------------------------------------------------
# Environment. Two common patterns -- pick whichever your cluster uses.
# Your HPC's docs (and the BuckAI HPC Handbook) tell you which one.
#
#   (a) Module-based activation:
#         module load miniconda3
#         source activate geoai-datacubes
#
#   (b) Direct conda init:
#         source /path/to/your/miniconda3/etc/profile.d/conda.sh
#         conda activate geoai-datacubes
# ---------------------------------------------------------------------------
# --- (a) module-based activation (uncomment and edit for your cluster) ---
# module purge
# module load miniconda3
source activate geoai-datacubes

# ---------------------------------------------------------------------------
# Run the pipeline. main.py reads its USER INPUT block from the top of the
# file -- edit that block (mission, AOI, dates, etc.) before submitting.
# ---------------------------------------------------------------------------
cd "${SLURM_SUBMIT_DIR}/modules/sentinel_pipeline"

echo "[$(date '+%F %T')] Starting fetch on $(hostname) (job ${SLURM_JOB_ID})"
python main.py
echo "[$(date '+%F %T')] Done."
