"""Aggregate per-class benchmark JSONs into a single LULC leaderboard.

`benchmark_lulc_class.py` writes one JSON file per ESA-WorldCover class
with a `per_model` dict (LR / RF / XGB results on val + test). This
script reads every such JSON in `--inputs-dir` (default: `/tmp` plus
`notebooks/_ml_outputs/leaderboard/`), pivots them into a long-format
DataFrame -- one row per (class, model) -- and writes:

    notebooks/lulc_leaderboard.csv
    notebooks/lulc_leaderboard.parquet     (when pyarrow is available)

The CSV is the human-readable, git-diffable artefact. The Parquet is for
fast `pd.read_parquet` from the notebook display cell.

The leaderboard can also include U-Net rows: pass `--unet-json
path/to/unet_metrics.json` (a sidecar written by the DL training cell in
nb 01) and the U-Net row gets added with the same metric grid.

Usage:
    python notebooks/aggregate_leaderboard.py
    python notebooks/aggregate_leaderboard.py --inputs-dir /tmp
    python notebooks/aggregate_leaderboard.py \
        --inputs-dir /tmp --unet-json /tmp/unet_class80.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

CLASS_NAMES = {
    10: "tree_cover",
    20: "shrubland",
    30: "grassland",
    40: "cropland",
    50: "built_up",
    60: "bare",
    70: "snow_ice",
    80: "water",
    90: "wetland",
    95: "mangroves",
    100: "moss_lichen",
}


def find_class_jsons(inputs_dirs):
    """Return a list of (class_id, json_path) for every lulc_<id>.json found."""
    found = []
    seen_ids = set()
    for d in inputs_dirs:
        if not d.exists():
            continue
        for p in sorted(d.glob("lulc_*.json")):
            stem = p.stem  # "lulc_50" or "lulc_50_built_up" -> 50
            try:
                cid = int(stem.split("_")[1])
            except (IndexError, ValueError):
                continue
            # newest copy of each class wins (sorted name -> mtime as tiebreak)
            if cid in seen_ids:
                continue
            seen_ids.add(cid)
            found.append((cid, p))
    return found


def explode_one(rec):
    """One benchmark JSON -> 1 row per (model, split=test) of per-model metrics."""
    cid = rec["class_id"]
    cname = rec.get("class_name") or CLASS_NAMES.get(cid, f"class_{cid}")
    rows = []
    for model_name, m in rec["per_model"].items():
        for split in ("val", "test"):
            s = m.get(split, {})
            rows.append({
                "class_id":         cid,
                "class_name":       cname,
                "model":            model_name,
                "split":            split,
                "threshold":        float(m.get("threshold", 0.5)),
                "n":                int(s.get("n", 0)),
                "n_pos":            int(s.get("n_pos", 0)),
                "pos_frac":         float(s.get("n_pos", 0)) / max(1, s.get("n", 1)),
                "acc":              float(s.get("acc", float("nan"))),
                "prec":             float(s.get("prec", float("nan"))),
                "rec":              float(s.get("rec", float("nan"))),
                "f1":               float(s.get("f1", float("nan"))),
                "iou":              float(s.get("iou", float("nan"))),
                "auc":              float(s.get("auc", float("nan"))),
                # Provenance: which feature set the row was trained on.
                "features":         ",".join(rec.get("feature_bands", [])),
                "n_train_balanced": int(rec.get("n_train", 0)),
                "pos_frac_train":   float(rec.get("pos_frac_train", float("nan"))),
            })
    return rows


def add_unet_rows(rows, unet_path):
    """Append U-Net rows from a sidecar JSON written by the nb 01 DL cell.

    Expected format (one per class):
        {"class_id": 80, "class_name": "water",
         "model": "U-Net",
         "val":  {"acc": ..., "prec": ..., "rec": ..., "f1": ..., "iou": ..., "auc": ...},
         "test": {"acc": ..., ...},
         "feature_bands": ["...", ...],
         "n_train_tiles": 246, "pos_frac_train": 0.31}
    """
    rec = json.loads(Path(unet_path).read_text())
    cid = rec["class_id"]
    cname = rec.get("class_name") or CLASS_NAMES.get(cid, f"class_{cid}")
    for split in ("val", "test"):
        s = rec.get(split, {})
        rows.append({
            "class_id":         cid,
            "class_name":       cname,
            "model":            rec.get("model", "U-Net"),
            "split":            split,
            "threshold":        float(rec.get("threshold", 0.5)),
            "n":                int(s.get("n", 0)),
            "n_pos":            int(s.get("n_pos", 0)),
            "pos_frac":         float(s.get("n_pos", 0)) / max(1, s.get("n", 1)),
            "acc":              float(s.get("acc", float("nan"))),
            "prec":             float(s.get("prec", float("nan"))),
            "rec":              float(s.get("rec", float("nan"))),
            "f1":               float(s.get("f1", float("nan"))),
            "iou":              float(s.get("iou", float("nan"))),
            "auc":              float(s.get("auc", float("nan"))),
            "features":         ",".join(rec.get("feature_bands", [])),
            "n_train_balanced": int(rec.get("n_train_tiles", 0)),
            "pos_frac_train":   float(rec.get("pos_frac_train", float("nan"))),
        })
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--inputs-dir", action="append", type=Path, default=None,
        help="Directory holding lulc_<id>.json files. Repeatable. "
             "Default: /tmp/ and notebooks/_ml_outputs/leaderboard/",
    )
    ap.add_argument(
        "--unet-json", action="append", type=Path, default=[],
        help="Optional sidecar JSON of U-Net metrics. Repeatable.",
    )
    ap.add_argument(
        "--out-csv", type=Path,
        default=Path("notebooks/lulc_leaderboard.csv"),
        help="Output CSV path (default notebooks/lulc_leaderboard.csv).",
    )
    ap.add_argument(
        "--out-parquet", type=Path,
        default=Path("notebooks/lulc_leaderboard.parquet"),
        help="Output Parquet path (default notebooks/lulc_leaderboard.parquet).",
    )
    args = ap.parse_args()

    inputs_dirs = args.inputs_dir or [
        Path("/tmp"),
        Path("notebooks/_ml_outputs/leaderboard"),
    ]

    found = find_class_jsons(inputs_dirs)
    if not found and not args.unet_json:
        print("No lulc_*.json inputs found. Run benchmark_lulc_class.py first.",
              file=sys.stderr)
        sys.exit(1)

    rows = []
    for cid, p in found:
        rec = json.loads(p.read_text())
        rows.extend(explode_one(rec))
        print(f"loaded class {cid} from {p}")

    for up in args.unet_json:
        try:
            add_unet_rows(rows, up)
            print(f"loaded U-Net record from {up}")
        except Exception as e:
            print(f"could not parse U-Net record {up}: {e}", file=sys.stderr)

    df = pd.DataFrame(rows)
    if df.empty:
        print("Empty leaderboard -- nothing written.", file=sys.stderr)
        sys.exit(1)

    # Stable canonical ordering: class_id asc, model in a fixed order, split first
    model_order = {"LogReg": 0, "RF": 1, "XGB": 2, "U-Net": 3}
    df["_model_o"] = df["model"].map(model_order).fillna(99).astype(int)
    df = df.sort_values(["class_id", "_model_o", "split"]).drop(columns="_model_o")
    df = df.reset_index(drop=True)

    args.out_csv.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out_csv, index=False, float_format="%.4f")
    print(f"\nwrote {args.out_csv}  ({len(df)} rows, "
          f"{df['class_id'].nunique()} classes, {df['model'].nunique()} models)")

    try:
        df.to_parquet(args.out_parquet, index=False)
        print(f"wrote {args.out_parquet}")
    except Exception as e:
        print(f"(parquet skipped: {e})")


if __name__ == "__main__":
    main()
