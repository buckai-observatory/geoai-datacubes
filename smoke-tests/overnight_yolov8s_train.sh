#!/bin/bash
# Overnight: yolov8s training + post-training nb 02 re-run.
# Single fire-and-forget script so the user can sleep.
#
# Outputs:
#   /tmp/overnight_train.log -- training stdout/stderr
#   /tmp/overnight_nb.log    -- post-train notebook re-execution log
#   /tmp/overnight_status    -- single-word status: TRAINING / TRAINED / DONE / TRAIN_FAILED
set -uo pipefail
cd /Users/moortgat/Documents/buckAI_observatory/Website/Github/geoai-datacubes
export PATH=/opt/anaconda3/envs/h2oval/bin:$PATH
export PYTHONPATH=/Users/moortgat/Documents/buckAI_observatory/Website/Github/geoai-datacubes
export OMP_NUM_THREADS=2
export KMP_DUPLICATE_LIB_OK=TRUE
# MPS has limited operator coverage; let unsupported ops fall back to
# CPU silently instead of raising NotImplementedError.
export PYTORCH_ENABLE_MPS_FALLBACK=1

TRAIN_LOG=/tmp/overnight_train.log
NB_LOG=/tmp/overnight_nb.log
STATUS=/tmp/overnight_status

echo "TRAINING" > $STATUS
echo "[overnight] start at $(date -u +%Y-%m-%dT%H:%M:%SZ)" | tee $TRAIN_LOG

# ============================================================
# 1. Train yolov8s for 80 epochs on MPS
# ============================================================
python - >> $TRAIN_LOG 2>&1 <<'PY'
import time, sys
from pathlib import Path
from ultralytics import YOLO
import logging
logging.getLogger("ultralytics").setLevel(logging.INFO)

t0 = time.time()
m = YOLO("yolov8s.pt")
try:
    m.train(
        data="notebooks/_outputs_obj/yolo/data.yaml",
        epochs=80,
        imgsz=512,
        batch=8,
        device="mps",
        project="notebooks/_outputs_obj/runs",
        name="building_det_yolov8s_3cities",
        exist_ok=True,
        seed=42,
        deterministic=True,
        verbose=True,
        pretrained=True,
        save=True,
        save_period=-1,
        plots=True,
        workers=2,
        degrees=15.0,
        scale=0.5,
        translate=0.1,
    )
    print(f"[overnight] training done in {(time.time()-t0)/3600:.2f} h", flush=True)
    sys.exit(0)
except Exception as e:
    print(f"[overnight] TRAINING CRASHED: {type(e).__name__}: {e}", flush=True)
    sys.exit(1)
PY
TRAIN_RC=$?

echo "[overnight] training finished at $(date -u +%Y-%m-%dT%H:%M:%SZ) rc=$TRAIN_RC" >> $TRAIN_LOG

if [ $TRAIN_RC -ne 0 ]; then
    echo "TRAIN_FAILED" > $STATUS
    echo "[overnight] STOP: training failed, skipping notebook re-run" >> $TRAIN_LOG
    exit 1
fi

# Sanity-check that the checkpoint actually landed.
BEST_PT="notebooks/_outputs_obj/runs/building_det_yolov8s_3cities/weights/best.pt"
if [ ! -f "$BEST_PT" ]; then
    echo "TRAIN_FAILED" > $STATUS
    echo "[overnight] STOP: training reported success but best.pt missing at $BEST_PT" >> $TRAIN_LOG
    exit 1
fi

echo "TRAINED" > $STATUS
echo "[overnight] checkpoint OK at $BEST_PT  ($(stat -f%z $BEST_PT) bytes)" >> $TRAIN_LOG

# ============================================================
# 2. Re-run nb 02 end-to-end with the new checkpoint
# ============================================================
bash /tmp/run_nb02.sh > $NB_LOG 2>&1

echo "DONE" > $STATUS
echo "[overnight] all done at $(date -u +%Y-%m-%dT%H:%M:%SZ)" >> $TRAIN_LOG
