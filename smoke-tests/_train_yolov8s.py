"""Train yolov8s on the 3-city YOLO-format dataset.

Standalone Python driver used by `smoke-tests/train_yolov8s.slurm`. Runs
identically on a laptop (with `--device cpu` or `--device mps`) and on a
GPU cluster node (with `--device cuda`).

Reads the YOLO directory layout produced by `notebooks/02_building_detection.ipynb`
section 6 (images/train, images/val, images/test + a data.yaml that
points to them). Writes the trained checkpoint to
`notebooks/_outputs_obj/runs/building_det_yolov8s_3cities/weights/best.pt`,
which is exactly where the notebook's section-9 cache lookup checks for it.

Usage:
    python smoke-tests/_train_yolov8s.py --device cuda --epochs 200
    python smoke-tests/_train_yolov8s.py --device cpu  --epochs 30
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--device",  type=str, default="cuda",
                    help="cuda | mps | cpu  (default: cuda for HPC GPU nodes).")
    ap.add_argument("--epochs",  type=int, default=200,
                    help="Number of training epochs. 200 is the headline; "
                         "30-80 is enough for a teaching demo.")
    ap.add_argument("--imgsz",   type=int, default=512)
    ap.add_argument("--batch",   type=int, default=16,
                    help="GPU batch size. Use 8 for MPS or CPU.")
    ap.add_argument("--workers", type=int, default=8,
                    help="Number of DataLoader workers. Match SLURM "
                         "--cpus-per-task.")
    ap.add_argument("--data-yaml", type=str,
                    default="notebooks/_outputs_obj/yolo/data.yaml")
    ap.add_argument("--project",   type=str,
                    default="notebooks/_outputs_obj/runs")
    ap.add_argument("--run-name",  type=str,
                    default="building_det_yolov8s_3cities")
    ap.add_argument("--weights",   type=str, default="yolov8s.pt",
                    help="Starting weights (Ultralytics or local .pt).")
    ap.add_argument("--seed",      type=int, default=42)
    args = ap.parse_args()

    data_yaml = Path(args.data_yaml)
    if not data_yaml.exists():
        sys.exit(f"data.yaml not found at {data_yaml}. "
                 "Run nb 02 sections 1-6 first to generate the YOLO layout.")

    from ultralytics import YOLO
    logging.getLogger("ultralytics").setLevel(logging.INFO)

    print(f"[train_yolov8s] device={args.device}  epochs={args.epochs}  "
          f"batch={args.batch}  imgsz={args.imgsz}  workers={args.workers}",
          flush=True)
    t0 = time.time()

    model = YOLO(args.weights)
    model.train(
        data=str(data_yaml),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=args.device,
        project=args.project,
        name=args.run_name,
        exist_ok=True,
        seed=args.seed,
        deterministic=True,
        verbose=True,
        pretrained=True,
        save=True,
        save_period=-1,
        plots=True,
        workers=args.workers,
        # Augmentation: scale + translate + rotation jitter on top of
        # the default mosaic + flips. Helps the model handle the wide
        # range of building footprint sizes a 512 m tile actually
        # contains (single-family houses ~ 10x10 m next to industrial
        # warehouses ~ 80x40 m).
        degrees=15.0,
        scale=0.5,
        translate=0.1,
    )

    elapsed_h = (time.time() - t0) / 3600.0
    print(f"\n[train_yolov8s] training done in {elapsed_h:.2f} h", flush=True)

    # Sanity-check that the checkpoint actually landed.
    best_pt = Path(args.project) / args.run_name / "weights" / "best.pt"
    if best_pt.exists():
        sz_mb = best_pt.stat().st_size / 1024 / 1024
        print(f"[train_yolov8s] checkpoint: {best_pt}  ({sz_mb:.1f} MB)",
              flush=True)
    else:
        sys.exit(f"[train_yolov8s] WARN training reported success but "
                 f"best.pt is missing at {best_pt}")


if __name__ == "__main__":
    main()
