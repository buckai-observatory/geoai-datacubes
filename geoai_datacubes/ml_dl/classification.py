"""Pixel-level and tile-level classification helpers.

Public helpers
--------------

Tabular / pixel-level (used by ``notebooks/01_classification.ipynb`` and
the ``benchmark_lulc_class.py`` CLI):

* :func:`harvest_pixels`     -- walk a :class:`LazyTileDataset` and
                                return ``(X, y)`` with per-band
                                normalisation applied via
                                ``apply_band_norm`` (band_meta-driven).
* :func:`balance_pos_neg`    -- random under-sampling of the negative
                                class to a given ratio.
* :func:`tune_threshold`     -- F1-optimal probability cut-off swept on
                                a held-out set.
* :func:`binary_pixel_metrics` -- per-class confusion-matrix dict
                                  (accuracy, precision, recall, F1,
                                  IoU, AUC) for a single binary target.
* :func:`predict_with_threshold` -- ``proba >= threshold`` for any
                                    sklearn / XGB classifier.

Tile-level / U-Net evaluation:

* :func:`full_metrics`        -- aggregate a torch model's output across
                                 a ``DataLoader`` and report the same
                                 per-class dict.
* :func:`class_filtered_indices` -- pick tile indices with a minimum
                                    positive-class fraction.
* :func:`pick_class_balanced_tiles` -- pick N tiles spanning a
                                       positive-fraction range, useful
                                       for diagnostic figures.

All of these were previously defined inline in ``01_classification.ipynb``.
The notebook now imports from here so the same code paths run under
``benchmark_lulc_class.py`` (CLI), ``benchmark_unet_class.py`` (CLI),
and the notebook itself.
"""
from __future__ import annotations

from typing import Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from ..preprocessing.band_ops import (
    apply_band_norm,
    get_band_norm,
)


# ============================================================
# Tabular / pixel-level helpers
# ============================================================

def _normalise_feature_arr(arr: np.ndarray, band_names: Sequence[str],
                           mission_profiles=None,
                           overrides: Optional[Mapping[str, Tuple]] = None,
                           ) -> np.ndarray:
    """Apply ``apply_band_norm`` to each channel of an ``(H, W, C)`` array.

    The normalisation recipe per band is looked up via
    :func:`get_band_norm` (so a band declared in ``MISSION_PROFILES``'s
    ``band_meta`` overrides the regex-based default). Pure-Python no-ops
    are cheap; the only cost is per-band traversal.
    """
    out = arr.astype(np.float32, copy=True)
    for ci, name in enumerate(band_names):
        recipe = get_band_norm(name,
                               mission_profiles=mission_profiles,
                               override=overrides)
        if recipe[0] == "passthrough":
            continue
        out[..., ci] = apply_band_norm(out[..., ci], recipe)
    return out


def harvest_pixels(
    zarr_path,
    *,
    split: str,
    feature_bands: Sequence[str],
    label_band: str,
    label_remap: Mapping[int, int],
    split_ratios: Tuple[float, float, float] = (0.70, 0.15, 0.15),
    split_method: str = "random",
    tile_size: int = 64,
    stride: int = 64,
    nan_handling: str = "drop",
    derived_arrays: Optional[Mapping[str, np.ndarray]] = None,
    normalise: bool = True,
    mission_profiles=None,
    norm_overrides: Optional[Mapping[str, Tuple]] = None,
    seed: int = 42,
) -> Tuple[np.ndarray, np.ndarray]:
    """Walk a ``LazyTileDataset`` and return ``(X, y)`` for one split.

    Parameters
    ----------
    zarr_path : path-like
        Per-city Zarr cube path (or any path accepted by
        :class:`LazyTileDataset`).
    split : str
        ``"train"``, ``"val"``, or ``"test"``.
    feature_bands : list[str]
        Mission-prefixed band names (e.g. ``"Sentinel-2_B04"``) to pull
        from the cube.
    label_band : str
        Mission-prefixed label band, typically
        ``"ESA-WorldCover_LULC"``.
    label_remap : dict[int, int]
        Class-id remap, e.g. ``{80: 1}`` for binary water-vs-rest.
    derived_arrays : dict[str, np.ndarray], optional
        Pre-computed full-cube feature channels (e.g.
        ``{"DEM_gradient_mag": grad_array}``). They are sliced against
        the same tile window as the cube bands.
    normalise : bool, default True
        Apply :func:`apply_band_norm` per band using the recipe declared
        on each band's ``band_meta`` entry. Set ``False`` for tree-based
        models that don't care about feature scaling.
    mission_profiles : dict, optional
        Overrides the default ``MISSION_PROFILES`` import.
    norm_overrides : dict, optional
        Per-band recipe overrides (e.g.
        ``{"Copernicus-DEM_DEM": ("mean_subtract", 500.0)}``).
    seed : int
        Forwarded to :class:`LazyTileDataset`.

    Returns
    -------
    X : ndarray of shape (N_pixels, n_features)
    y : ndarray of shape (N_pixels,)  -- 0 / 1
    """
    # Local imports so the module is cheap to import for sklearn-only users
    from ..preprocessing import LazyTileDataset
    from ..fetch.missions import MISSION_PROFILES

    if mission_profiles is None:
        mission_profiles = MISSION_PROFILES

    ds = LazyTileDataset(
        cube_path=str(zarr_path),
        feature_bands=list(feature_bands),
        label_band=label_band,
        label_remap=dict(label_remap),
        tile_size=tile_size, stride=stride,
        split=split,
        train_val_test_split=split_ratios,
        split_method=split_method,
        nan_handling=nan_handling,
        augment=False,
        return_window_xy=True,
        seed=seed,
    )

    n_extra = len(derived_arrays) if derived_arrays else 0
    n_feat = len(feature_bands) + n_extra

    xs: List[np.ndarray] = []
    ys: List[np.ndarray] = []
    for i in range(len(ds)):
        feat_t, lab_t, meta = ds[i]
        if not meta.get("valid_tile", True):
            continue
        # feat_t shape: (C, H, W); rearrange to (H, W, C) for per-band ops.
        f = feat_t.numpy().transpose(1, 2, 0)
        if normalise:
            f = _normalise_feature_arr(
                f, feature_bands,
                mission_profiles=mission_profiles,
                overrides=norm_overrides,
            )
        if derived_arrays:
            x0, y0 = int(meta["x"]), int(meta["y"])
            extras = []
            shape_ok = True
            for name, arr in derived_arrays.items():
                window = arr[y0:y0 + tile_size, x0:x0 + tile_size]
                if window.shape != f.shape[:2]:
                    # Edge tile whose derived-array window is short. Skip
                    # the whole tile rather than mismatch the column count
                    # across the harvest -- a partial-extras tile would
                    # produce X rows with 6 features while every other
                    # tile produced 7, breaking the concatenate downstream.
                    shape_ok = False
                    break
                extras.append(window[..., None].astype(np.float32))
            if not shape_ok:
                continue
            if extras:
                f = np.concatenate([f] + extras, axis=-1)

        fx = f.reshape(-1, f.shape[-1])
        fy = lab_t.numpy().reshape(-1)
        keep = (fy >= 0) & np.isfinite(fx).all(axis=1)
        xs.append(fx[keep])
        ys.append(fy[keep])

    if not xs:
        return np.empty((0, n_feat), dtype=np.float32), \
               np.empty((0,),       dtype=np.int64)
    return np.concatenate(xs, axis=0), np.concatenate(ys, axis=0)


def balance_pos_neg(X: np.ndarray, y: np.ndarray, max_ratio: int = 5,
                    seed: int = 42) -> Tuple[np.ndarray, np.ndarray]:
    """Random under-sampling of the majority (negative) class.

    Caps the negative-to-positive ratio at ``max_ratio``. Shuffles the
    survivor indices before returning so a downstream classifier sees a
    well-mixed feed.
    """
    rng = np.random.default_rng(seed)
    pos = np.where(y == 1)[0]
    neg = np.where(y == 0)[0]
    if len(pos) == 0:
        return X, y
    cap = max_ratio * len(pos)
    if len(neg) > cap:
        neg = rng.choice(neg, size=cap, replace=False)
    idx = np.concatenate([pos, neg])
    rng.shuffle(idx)
    return X[idx], y[idx]


def tune_threshold(model, X: np.ndarray, y: np.ndarray) -> float:
    """Sweep ``predict_proba`` thresholds; return the F1-optimal one.

    Works with any sklearn-compatible classifier (LR / RF / XGBClassifier)
    that exposes ``predict_proba``. Returns ``0.5`` when the input has
    only a single class so the caller can fall back without branching.
    """
    from sklearn.metrics import precision_recall_curve

    if len(np.unique(y)) < 2:
        return 0.5
    proba = model.predict_proba(X)[:, 1]
    prec, rec, thr = precision_recall_curve(y, proba)
    f1 = 2 * prec * rec / np.clip(prec + rec, 1e-9, None)
    best = int(np.nanargmax(f1[:-1])) if len(thr) else 0
    return float(thr[best]) if len(thr) else 0.5


def binary_pixel_metrics(y_true: np.ndarray, y_pred: np.ndarray,
                         y_prob: Optional[np.ndarray] = None,
                         ) -> dict:
    """Per-pixel binary confusion-matrix metrics.

    ``y_prob`` is optional; if provided, AUC is included. The dict shape
    matches what ``benchmark_lulc_class.py`` writes per model, so the
    leaderboard aggregator can ingest it directly.
    """
    from sklearn.metrics import (accuracy_score, precision_score, recall_score,
                                 f1_score, jaccard_score, roc_auc_score)
    if len(y_true) == 0:
        return {"n": 0, "n_pos": 0, "acc": 0., "prec": 0., "rec": 0.,
                "f1": 0., "iou": 0., "auc": float("nan")}
    out = {
        "n":     int(y_true.size),
        "n_pos": int((y_true == 1).sum()),
        "acc":   float(accuracy_score(y_true, y_pred)),
        "prec":  float(precision_score(y_true, y_pred, zero_division=0)),
        "rec":   float(recall_score(y_true, y_pred, zero_division=0)),
        "f1":    float(f1_score(y_true, y_pred, zero_division=0)),
        "iou":   float(jaccard_score(y_true, y_pred, zero_division=0)),
    }
    if y_prob is not None and len(np.unique(y_true)) == 2:
        try:
            out["auc"] = float(roc_auc_score(y_true, y_prob))
        except ValueError:
            out["auc"] = float("nan")
    else:
        out["auc"] = float("nan")
    return out


def predict_with_threshold(model, X: np.ndarray, threshold: float) -> np.ndarray:
    """Apply ``proba >= threshold`` to a sklearn-compatible classifier."""
    proba = model.predict_proba(X)[:, 1]
    return (proba >= threshold).astype(np.int64)


# ============================================================
# Tile-level / U-Net helpers
# ============================================================

def full_metrics(model, loader, threshold: float = 0.5,
                 device: str = "cpu") -> dict:
    """Run a torch segmentation model over a ``DataLoader`` and aggregate.

    Returns the same dict shape as :func:`binary_pixel_metrics` so a
    leaderboard row can carry an LR / RF / XGB / U-Net result with one
    schema.

    Expects each batch from ``loader`` to be ``(x, y[, meta])`` where
    ``x`` is float32 of shape ``(B, C, H, W)`` and ``y`` is long of shape
    ``(B, H, W)`` with valid labels in ``{0, 1}`` and ignored pixels at
    ``-1``.
    """
    import torch
    ys, probs = [], []
    model.eval()
    with torch.no_grad():
        for batch in loader:
            if len(batch) == 3:
                x, y, _ = batch
            else:
                x, y = batch
            logits = model(x.to(device))
            p1 = torch.softmax(logits, dim=1)[:, 1].cpu().numpy().ravel()
            yy = y.numpy().ravel()
            keep = yy >= 0
            probs.append(p1[keep])
            ys.append(yy[keep])
    if not ys:
        return binary_pixel_metrics(np.empty(0, dtype=np.int64),
                                    np.empty(0, dtype=np.int64))
    y = np.concatenate(ys); p = np.concatenate(probs)
    yp = (p >= threshold).astype(np.int64)
    return binary_pixel_metrics(y, yp, y_prob=p)


def class_filtered_indices(ds, min_pos_frac: float) -> List[int]:
    """Return tile indices where the binary label has at least ``min_pos_frac``.

    ``ds`` is a :class:`LazyTileDataset` configured with a binary
    label_remap (so ``y[i] in {0, 1}`` per pixel). Use to skip tiles
    that contain no instance of the target class -- common for rare
    classes where the random-split harvest is dominated by empties.
    """
    keep = []
    for i in range(len(ds)):
        item = ds[i]
        y = (item[1] if len(item) >= 2 else item).numpy()
        valid = y >= 0
        if not valid.any():
            continue
        pos = float((y == 1).sum()) / float(valid.sum())
        if pos >= min_pos_frac:
            keep.append(i)
    return keep


def pick_class_balanced_tiles(ds, pos_frac_range: Tuple[float, float],
                              n_show: int = 6,
                              rng: Optional[np.random.Generator] = None,
                              ) -> List[int]:
    """Pick ``n_show`` tile indices that span a positive-fraction range.

    Useful for diagnostic figure cells where you want a mix of
    background-heavy and class-heavy tiles to render. ``rng`` is
    optional -- when ``None`` a per-call generator is created.
    """
    if rng is None:
        rng = np.random.default_rng()
    lo, hi = pos_frac_range
    candidates = []
    for i in range(len(ds)):
        item = ds[i]
        y = (item[1] if len(item) >= 2 else item).numpy()
        valid = y >= 0
        if not valid.any():
            continue
        pos = float((y == 1).sum()) / float(valid.sum())
        if lo <= pos <= hi:
            candidates.append(i)
    if len(candidates) <= n_show:
        return candidates
    return list(rng.choice(candidates, size=n_show, replace=False))


__all__ = [
    "harvest_pixels",
    "balance_pos_neg",
    "tune_threshold",
    "binary_pixel_metrics",
    "predict_with_threshold",
    "full_metrics",
    "class_filtered_indices",
    "pick_class_balanced_tiles",
]
