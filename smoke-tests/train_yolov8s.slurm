#!/bin/bash
#SBATCH --job-name=geoai-yolov8s
#SBATCH --partition=gpu                # adjust for your cluster (e.g. gpu-a100, ampere)
#SBATCH --gres=gpu:1                   # one GPU is plenty for yolov8s
#SBATCH --time=04:00:00                # 200 epochs typically lands in 30-90 min on A100
#SBATCH --mem=32G
#SBATCH --cpus-per-task=8              # match `--workers 8` below
#SBATCH --output=smoke-tests/logs/%x.%j.out
#SBATCH --error=smoke-tests/logs/%x.%j.err
# ---------------------------------------------------------------------------
# Train yolov8s on the geoai-datacubes building-detection dataset on an HPC
# GPU node. Mirrors the laptop training cell in nb 02 -- same data, same
# model size, same augmentation -- but runs in ~30-60 min instead of
# ~13-15 h on Apple Silicon MPS.
#
# Prerequisites the cluster side must have done:
#   1. Repo cloned (or rsync'd) so `notebooks/_outputs_obj/yolo/` exists.
#      If you haven't run nb 02 sections 1-6 on the cluster yet, see
#      docs/HPC_QUICKSTART.md for how to regenerate the YOLO layout from
#      the bundled footprints + a fresh NAIP fetch.
#   2. A conda env with the packages in requirements.txt (run
#      `bash smoke-tests/check_env.sh` to verify before submitting).
#   3. The active env is on $PATH when the SLURM job starts -- typically
#      via `conda activate <envname>` in your ~/.bashrc or a job
#      preamble.
#
# Usage:
#   sbatch smoke-tests/train_yolov8s.slurm                 # uses --epochs 200
#   sbatch --export=ALL,EPOCHS=80 smoke-tests/train_yolov8s.slurm   # override
#
# After the job finishes, the trained checkpoint lands at:
#   notebooks/_outputs_obj/runs/building_det_yolov8s_3cities/weights/best.pt
# rsync that file back to your laptop and the nb 02 section-9 cache
# lookup picks it up automatically.
# ---------------------------------------------------------------------------
set -euo pipefail

# Resolve repo root from the SLURM submit dir (sbatch starts you in the
# directory you submitted from). When run interactively via `bash`, fall
# back to the script's own location.
if [ -n "${SLURM_SUBMIT_DIR:-}" ]; then
    REPO_ROOT="$SLURM_SUBMIT_DIR"
else
    REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fi
cd "$REPO_ROOT"
export PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}"

EPOCHS="${EPOCHS:-200}"
BATCH="${BATCH:-16}"
DEVICE="${DEVICE:-cuda}"

echo "=========================================================================="
echo "geoai-datacubes: train yolov8s"
echo "  REPO_ROOT  : $REPO_ROOT"
echo "  SLURM_JOB  : ${SLURM_JOB_ID:-(local, not sbatch)}"
echo "  GPU(s)     : ${CUDA_VISIBLE_DEVICES:-?} ($(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1))"
echo "  PYTHON     : $(command -v python)"
echo "  EPOCHS     : $EPOCHS"
echo "  BATCH      : $BATCH"
echo "  DEVICE     : $DEVICE"
echo "=========================================================================="

# Run the training driver. Same Python you'd run on a laptop with
# --device cpu / mps -- the cluster just gets cuda.
python smoke-tests/_train_yolov8s.py \
    --device "$DEVICE" \
    --epochs "$EPOCHS" \
    --batch  "$BATCH" \
    --imgsz  512 \
    --workers 8

echo
echo "=========================================================================="
echo "Done. Checkpoint at:"
ls -la notebooks/_outputs_obj/runs/building_det_yolov8s_3cities/weights/ 2>/dev/null || \
  echo "  (no weights/ folder -- training may have failed; check the .err file)"
echo "=========================================================================="
