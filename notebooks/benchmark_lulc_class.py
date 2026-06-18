"""Pixel-level binary benchmark for one ESA WorldCover LULC class.

Mirrors the headline pixel-level setup of `01_water_classification.ipynb`:
- Same three city Zarr cubes (Columbus, Cincinnati, Cleveland).
- Same feature set: Sentinel-2 (B02, B03, B04, B08) + Sentinel-1 (VV, VH).
- Same random-split LazyTileDataset wiring (water classification settled on
  random split because the rare-class block split produces unstable F1).
- Same train -> threshold-tune on val -> evaluate on test pipeline.

Output is a JSON line on stdout (and optionally a file) with the headline
metrics, so a wrapper agent can parse it without scraping prose:

    {"class_id": 10, "class_name": "tree_cover", "f1": 0.91, ...}

Usage:
    python benchmark_lulc_class.py --class-id 50 --class-name built_up
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

# Make the pipeline modules importable
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "modules" / "sentinel_pipeline"))

# Honor the same OMP / torch single-thread guards as the notebook
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

# Heavy imports come after env vars
from lazy_dataset import LazyTileDataset


SEED = 42
LABEL_BAND = "ESA-WorldCover_LULC"
FEATURE_BANDS = [
    "Sentinel-2_B02", "Sentinel-2_B03", "Sentinel-2_B04", "Sentinel-2_B08",
    "Sentinel-1_VV",  "Sentinel-1_VH",
]
CITIES = ["columbus", "cincinnati", "cleveland"]
SPLIT_RATIOS = (0.70, 0.15, 0.15)
ZARR_DIR = REPO_ROOT / "notebooks" / "_ml_outputs" / "zarr"


def harvest_pixels(zarr_path, split, class_id, tile_size=64, stride=64):
    """Pull (X, y) for one (city, split). Binary label: 1 if LULC == class_id else 0."""
    ds = LazyTileDataset(
        cube_path=str(zarr_path),
        feature_bands=FEATURE_BANDS,
        label_band=LABEL_BAND,
        label_remap={int(class_id): 1},
        tile_size=tile_size, stride=stride,
        split=split,
        train_val_test_split=SPLIT_RATIOS,
        split_method="random",
        nan_handling="drop",
        augment=False,
        return_window_xy=True,
        seed=SEED,
    )
    xs, ys = [], []
    for i in range(len(ds)):
        feat_t, lab_t, meta = ds[i]
        if not meta["valid_tile"]:
            continue
        C = feat_t.shape[0]
        fx = feat_t.numpy().reshape(C, -1).T
        fy = lab_t.numpy().reshape(-1)
        keep = (fy >= 0) & np.isfinite(fx).all(axis=1)
        xs.append(fx[keep]); ys.append(fy[keep])
    if not xs:
        return np.empty((0, len(FEATURE_BANDS))), np.empty((0,), dtype=np.int64)
    return np.concatenate(xs, axis=0), np.concatenate(ys, axis=0)


def harvest_mixed(split, class_id):
    Xs, ys = [], []
    for city in CITIES:
        zarr_path = ZARR_DIR / f"{city}_cube.zarr"
        if not zarr_path.exists():
            raise SystemExit(f"Zarr cube missing: {zarr_path}. "
                             "Run notebook 01 first to populate the cubes.")
        X, y = harvest_pixels(zarr_path, split, class_id)
        if len(X): Xs.append(X); ys.append(y)
    if not Xs:
        return np.empty((0, len(FEATURE_BANDS))), np.empty((0,), dtype=np.int64)
    return np.concatenate(Xs), np.concatenate(ys)


def balance_pos_neg(X, y, max_ratio=5, seed=SEED):
    rng = np.random.default_rng(seed)
    pos = np.where(y == 1)[0]; neg = np.where(y == 0)[0]
    if len(pos) == 0:
        return X, y
    cap = max_ratio * len(pos)
    if len(neg) > cap:
        neg = rng.choice(neg, size=cap, replace=False)
    idx = np.concatenate([pos, neg]); rng.shuffle(idx)
    return X[idx], y[idx]


def tune_threshold(model, X, y):
    from sklearn.metrics import precision_recall_curve
    p = model.predict_proba(X)[:, 1]
    prec, rec, thr = precision_recall_curve(y, p)
    f1 = 2 * prec * rec / np.clip(prec + rec, 1e-9, None)
    best = int(np.nanargmax(f1[:-1]))
    return float(thr[best])


def metrics_at(model, X, y, threshold):
    from sklearn.metrics import (accuracy_score, precision_score, recall_score,
                                 f1_score, jaccard_score, roc_auc_score)
    if len(X) == 0:
        return {"n": 0, "n_pos": 0, "acc": 0., "prec": 0., "rec": 0.,
                "f1": 0., "iou": 0., "auc": float("nan")}
    p = model.predict_proba(X)[:, 1]
    yp = (p >= threshold).astype(np.int64)
    out = {
        "n":     int(y.size),
        "n_pos": int(y.sum()),
        "acc":   accuracy_score(y, yp),
        "prec":  precision_score(y, yp, zero_division=0),
        "rec":   recall_score(y, yp, zero_division=0),
        "f1":    f1_score(y, yp, zero_division=0),
        "iou":   jaccard_score(y, yp, zero_division=0),
    }
    try:    out["auc"] = roc_auc_score(y, p) if len(np.unique(y)) == 2 else float("nan")
    except: out["auc"] = float("nan")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--class-id",   type=int, required=True,
                    help="ESA WorldCover class id (e.g. 10, 30, 40, 50, 80).")
    ap.add_argument("--class-name", type=str, required=True,
                    help="Human-readable class label (e.g. tree_cover).")
    ap.add_argument("--output-json", type=str, default=None,
                    help="If set, also write the result JSON to this path.")
    args = ap.parse_args()

    print(f"[benchmark] class_id={args.class_id} ({args.class_name})", flush=True)

    # 1) Harvest
    t0 = time.time()
    X_train, y_train = harvest_mixed("train", args.class_id)
    X_val,   y_val   = harvest_mixed("val",   args.class_id)
    X_test,  y_test  = harvest_mixed("test",  args.class_id)
    print(f"[benchmark] harvest done in {time.time()-t0:.1f}s  "
          f"train={X_train.shape}  val={X_val.shape}  test={X_test.shape}",
          flush=True)
    print(f"[benchmark] positive fractions  "
          f"train={y_train.mean():.4f}  val={y_val.mean():.4f}  "
          f"test={y_test.mean():.4f}", flush=True)

    if y_train.sum() == 0:
        raise SystemExit(f"class {args.class_id} has zero positive pixels in "
                         f"training -- nothing to fit.")

    # 2) Balance training only
    X_train, y_train = balance_pos_neg(X_train, y_train)

    # 3) Three classifiers
    from sklearn.linear_model     import LogisticRegression
    from sklearn.ensemble         import RandomForestClassifier
    from sklearn.preprocessing    import StandardScaler
    from sklearn.pipeline         import Pipeline
    import xgboost as xgb

    n_pos = int(y_train.sum()); n_neg = int((y_train == 0).sum())
    spw = max(1.0, n_neg / max(1, n_pos))

    models = {}
    t0 = time.time()
    lr = Pipeline([("sc", StandardScaler()),
                   ("lr", LogisticRegression(max_iter=2000,
                                              class_weight="balanced",
                                              random_state=SEED))])
    lr.fit(X_train, y_train)
    models["LogReg"] = lr
    print(f"[benchmark] LR trained in {time.time()-t0:.1f}s", flush=True)

    t0 = time.time()
    rf = RandomForestClassifier(n_estimators=200, max_depth=14, n_jobs=2,
                                class_weight="balanced", random_state=SEED)
    rf.fit(X_train, y_train)
    models["RF"] = rf
    print(f"[benchmark] RF trained in {time.time()-t0:.1f}s", flush=True)

    t0 = time.time()
    xb = xgb.XGBClassifier(n_estimators=300, max_depth=6, learning_rate=0.1,
                           tree_method="hist", eval_metric="logloss",
                           scale_pos_weight=spw,
                           random_state=SEED, n_jobs=2)
    xb.fit(X_train, y_train)
    models["XGB"] = xb
    print(f"[benchmark] XGB trained in {time.time()-t0:.1f}s", flush=True)

    # 4) Tune threshold + evaluate
    per_model = {}
    for name, m in models.items():
        thr = tune_threshold(m, X_val, y_val) if y_val.sum() else 0.5
        per_model[name] = {
            "threshold": thr,
            "val":  metrics_at(m, X_val,  y_val,  thr),
            "test": metrics_at(m, X_test, y_test, thr),
        }

    best_name = max(per_model, key=lambda n: per_model[n]["test"]["f1"])
    result = {
        "class_id":   int(args.class_id),
        "class_name": args.class_name,
        "feature_bands": FEATURE_BANDS,
        "best_model": best_name,
        "best_f1":    float(per_model[best_name]["test"]["f1"]),
        "best_auc":   float(per_model[best_name]["test"]["auc"]),
        "per_model":  per_model,
        "n_train":    int(X_train.shape[0]),
        "n_val":      int(X_val.shape[0]),
        "n_test":     int(X_test.shape[0]),
        "pos_frac_train": float(y_train.mean()),
        "pos_frac_val":   float(y_val.mean())  if len(y_val)  else 0.0,
        "pos_frac_test":  float(y_test.mean()) if len(y_test) else 0.0,
    }

    print("[benchmark] === RESULT ===", flush=True)
    print(json.dumps(result, indent=2), flush=True)

    if args.output_json:
        with open(args.output_json, "w") as f:
            json.dump(result, f, indent=2)
        print(f"[benchmark] wrote {args.output_json}", flush=True)


if __name__ == "__main__":
    main()
