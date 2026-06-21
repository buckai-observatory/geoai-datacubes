"""Tile-level U-Net benchmark for one ESA WorldCover LULC class.

Mirrors `benchmark_lulc_class.py` (which does LR / RF / XGB at the pixel
level) but trains a small U-Net at the tile level for the same binary
target. Writes a sidecar JSON in the format expected by
`aggregate_leaderboard.py --unet-json ...` so the row joins the per-pixel
leaderboard cleanly:

    {"class_id": 80, "class_name": "water", "model": "U-Net",
     "val": {...metrics...}, "test": {...metrics...},
     "feature_bands": [...], "n_train_tiles": N, "pos_frac_train": F}

Usage:
    python notebooks/benchmark_unet_class.py \
        --class-id 50 --class-name built_up \
        --output-json /tmp/unet_class50.json
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

# Single-thread guards consistent with the pixel-level benchmark.
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from geoai_datacubes.preprocessing import LazyTileDataset
from geoai_datacubes.ml_dl import WaterUNet


SEED = 42
LABEL_BAND = "ESA-WorldCover_LULC"
FEATURE_BANDS = [
    "Sentinel-2_B02", "Sentinel-2_B03", "Sentinel-2_B04", "Sentinel-2_B08",
    "Sentinel-1_VV",  "Sentinel-1_VH",
]
CITIES = ["columbus", "cincinnati", "cleveland"]
SPLIT_RATIOS = (0.70, 0.15, 0.15)
TILE_SIZE = 64
STRIDE    = 64
ZARR_DIR  = REPO_ROOT / "notebooks" / "_ml_outputs" / "zarr"


def build_dataset(city, split, class_id):
    zarr_path = ZARR_DIR / f"{city}_cube.zarr"
    if not zarr_path.exists():
        raise SystemExit(f"Zarr cube missing: {zarr_path}. "
                         "Run notebook 01 first to populate the cubes.")
    return LazyTileDataset(
        cube_path=str(zarr_path),
        feature_bands=FEATURE_BANDS,
        label_band=LABEL_BAND,
        label_remap={int(class_id): 1},
        tile_size=TILE_SIZE, stride=STRIDE,
        split=split,
        train_val_test_split=SPLIT_RATIOS,
        split_method="random",
        nan_handling="drop",
        augment=(split == "train"),
        return_window_xy=True,   # 3-tuple return so per-tile meta is available
        seed=SEED,
    )


def evaluate(model, loaders, device, threshold=0.5):
    """Return per-split dict with accuracy / prec / rec / F1 / IoU / AUC."""
    import torch
    from sklearn.metrics import (accuracy_score, precision_score, recall_score,
                                 f1_score, jaccard_score, roc_auc_score)
    out = {}
    model.eval()
    for split, loader in loaders.items():
        ys, ps = [], []
        with torch.no_grad():
            for x, y, meta in loader:
                logits = model(x.to(device))
                prob1  = torch.softmax(logits, dim=1)[:, 1].cpu().numpy().ravel()
                yy = y.numpy().ravel()
                keep = yy >= 0
                ps.append(prob1[keep]); ys.append(yy[keep])
        if not ys:
            out[split] = {"n": 0, "n_pos": 0, "acc": 0., "prec": 0., "rec": 0.,
                          "f1": 0., "iou": 0., "auc": float("nan")}
            continue
        y = np.concatenate(ys); p = np.concatenate(ps)
        yp = (p >= threshold).astype(np.int64)
        rec = {
            "n":     int(y.size),
            "n_pos": int(y.sum()),
            "acc":   accuracy_score(y, yp),
            "prec":  precision_score(y, yp, zero_division=0),
            "rec":   recall_score(y, yp, zero_division=0),
            "f1":    f1_score(y, yp, zero_division=0),
            "iou":   jaccard_score(y, yp, zero_division=0),
        }
        try: rec["auc"] = roc_auc_score(y, p) if len(np.unique(y)) == 2 else float("nan")
        except Exception: rec["auc"] = float("nan")
        out[split] = rec
    return out


def tune_threshold(model, val_loader, device):
    """Sweep probability thresholds on val; return F1-optimal threshold."""
    import torch
    from sklearn.metrics import precision_recall_curve
    ys, ps = [], []
    model.eval()
    with torch.no_grad():
        for x, y, meta in val_loader:
            logits = model(x.to(device))
            prob1  = torch.softmax(logits, dim=1)[:, 1].cpu().numpy().ravel()
            yy = y.numpy().ravel()
            keep = yy >= 0
            ps.append(prob1[keep]); ys.append(yy[keep])
    if not ys:
        return 0.5
    y = np.concatenate(ys); p = np.concatenate(ps)
    if y.sum() == 0 or y.sum() == len(y):
        return 0.5
    prec, rec, thr = precision_recall_curve(y, p)
    f1 = 2 * prec * rec / np.clip(prec + rec, 1e-9, None)
    best = int(np.nanargmax(f1[:-1]))
    return float(thr[best])


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--class-id",   type=int, required=True)
    ap.add_argument("--class-name", type=str, required=True)
    ap.add_argument("--epochs",     type=int, default=20)
    ap.add_argument("--batch-size", type=int, default=16)
    ap.add_argument("--lr",         type=float, default=1e-3)
    ap.add_argument("--base",       type=int, default=24)
    ap.add_argument("--output-json", type=str, default=None)
    args = ap.parse_args()

    import torch
    from torch.utils.data import DataLoader, ConcatDataset
    torch.manual_seed(SEED); np.random.seed(SEED)
    device = "cuda" if torch.cuda.is_available() else "cpu"

    print(f"[unet] class_id={args.class_id} ({args.class_name}) device={device}",
          flush=True)

    t0 = time.time()
    train_ds = ConcatDataset([build_dataset(c, "train", args.class_id) for c in CITIES])
    val_ds   = ConcatDataset([build_dataset(c, "val",   args.class_id) for c in CITIES])
    test_ds  = ConcatDataset([build_dataset(c, "test",  args.class_id) for c in CITIES])
    print(f"[unet] datasets ready in {time.time()-t0:.1f}s  "
          f"train={len(train_ds)} val={len(val_ds)} test={len(test_ds)}", flush=True)

    if len(train_ds) == 0:
        raise SystemExit("Training split has 0 valid tiles. "
                         "Did the harvest helpers filter everything?")

    # Per-tile positive fraction (informational only -- never use the label
    # for sampler weights because the segmentation loss handles the imbalance
    # via `pos_weight`).
    pos = 0; total = 0
    for i in range(len(train_ds)):
        _, y, _ = train_ds[i]
        yn = y.numpy()
        pos += int((yn == 1).sum())
        total += int((yn >= 0).sum())
    pos_frac_train = pos / max(1, total)
    print(f"[unet] pos_frac_train pixel-level = {pos_frac_train:.4f}", flush=True)

    train_loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True,
                              num_workers=0, drop_last=False)
    val_loader   = DataLoader(val_ds,   batch_size=args.batch_size, shuffle=False,
                              num_workers=0)
    test_loader  = DataLoader(test_ds,  batch_size=args.batch_size, shuffle=False,
                              num_workers=0)

    in_ch = len(FEATURE_BANDS)
    model = WaterUNet(in_channels=in_ch, n_classes=2, base=args.base).to(device)
    opt   = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=args.epochs)
    # CrossEntropy with ignore_index=-1 so NaN-fill positions don't drive grad
    loss_fn = torch.nn.CrossEntropyLoss(ignore_index=-1)

    # ---- Train + save best-val checkpoint --------------------------------
    best_val_f1 = -1.0
    best_state  = copy.deepcopy(model.state_dict())
    for epoch in range(args.epochs):
        model.train()
        t1 = time.time()
        tot, n_batches = 0.0, 0
        for x, y, meta in train_loader:
            opt.zero_grad()
            logits = model(x.to(device))
            loss = loss_fn(logits, y.to(device).long())
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            opt.step()
            tot += float(loss.item()); n_batches += 1
        sched.step()

        # quick val F1 for early-stopping signal
        val_thr = 0.5
        val_metrics = evaluate(model, {"val": val_loader}, device, val_thr)["val"]
        marker = ""
        if val_metrics["f1"] > best_val_f1:
            best_val_f1 = val_metrics["f1"]
            best_state  = copy.deepcopy(model.state_dict())
            marker = " *"
        print(f"[unet] epoch {epoch+1:02d}/{args.epochs}  "
              f"loss={tot/max(1,n_batches):.4f}  "
              f"val_f1={val_metrics['f1']:.4f}  "
              f"({time.time()-t1:.1f}s){marker}", flush=True)

    # Restore best-val weights for the final metric pass
    model.load_state_dict(best_state)

    # ---- Tune threshold on val, then evaluate on val + test --------------
    thr = tune_threshold(model, val_loader, device)
    final = evaluate(model, {"val": val_loader, "test": test_loader}, device, thr)
    print(f"[unet] final threshold={thr:.3f}", flush=True)

    result = {
        "class_id":       int(args.class_id),
        "class_name":     args.class_name,
        "model":          "U-Net",
        "architecture":   "WaterUNet",
        "feature_bands":  FEATURE_BANDS,
        "tile_size":      TILE_SIZE,
        "epochs":         args.epochs,
        "batch_size":     args.batch_size,
        "lr":             args.lr,
        "threshold":      thr,
        "n_train_tiles":  len(train_ds),
        "n_val_tiles":    len(val_ds),
        "n_test_tiles":   len(test_ds),
        "pos_frac_train": pos_frac_train,
        "val":            final["val"],
        "test":           final["test"],
    }

    print("[unet] === RESULT ===", flush=True)
    print(json.dumps(result, indent=2), flush=True)

    if args.output_json:
        with open(args.output_json, "w") as f:
            json.dump(result, f, indent=2)
        print(f"[unet] wrote {args.output_json}", flush=True)


if __name__ == "__main__":
    main()
