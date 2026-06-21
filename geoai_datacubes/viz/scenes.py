"""Scene-level visualisation helpers: open, summarise, stretch, show.

All functions operate on a single scene -- the
``<Mission>_full_size.tiff`` that ``fetch_sentinel_data`` writes. Multi-
scene / cube-level helpers will land in a sibling module when the
need arises.

Function naming is preserved verbatim from the notebooks that grew
them so a tour-notebook cell that used to read::

    def stretch01(a, lo=2, hi=98): ...

becomes the one-liner::

    from geoai_datacubes.viz import stretch01

with no rename gymnastics.
"""
from __future__ import annotations

import glob
import json
import os
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
import rasterio


# ============================================================
# Scene I/O
# ============================================================

def find_response(scene_dir) -> str:
    """Return the path to the ``<Mission>_full_size.tiff`` in ``scene_dir``.

    The fetcher writes one scene folder per (mission, time, scene-id)
    with a single ``*_full_size.tiff`` inside. Older fetches under the
    pre-rename convention wrote ``response.tiff``; we accept that as a
    fallback so historical scenes still open.

    Raises ``FileNotFoundError`` if neither pattern matches.
    """
    scene_dir = str(scene_dir)
    candidates = sorted(glob.glob(os.path.join(scene_dir, "*_full_size.tiff")))
    if not candidates:
        candidates = sorted(glob.glob(os.path.join(scene_dir, "response.tiff")))
    if not candidates:
        raise FileNotFoundError(f"No *_full_size.tiff in {scene_dir}")
    return candidates[0]


def open_response(scene_dir):
    """Open a fetched scene and return its array + metadata as a 7-tuple.

    Parameters
    ----------
    scene_dir : path-like
        Folder containing a single ``*_full_size.tiff`` (the standard
        output layout of ``fetch_sentinel_data``).

    Returns
    -------
    tuple
        ``(arr, descs, prof, bbox, xform, crs, tiff)`` where

          - ``arr``   is the ``(C, H, W)`` numpy array,
          - ``descs`` is the list of band descriptions (one per channel),
          - ``prof``  is a copy of the rasterio profile dict,
          - ``bbox``  is the ``rasterio.coords.BoundingBox``,
          - ``xform`` is the affine transform,
          - ``crs``   is the CRS object, and
          - ``tiff``  is the absolute file path.

    The 7-tuple is deliberately wide because consumer code typically
    needs more than just the array (a CRS for reprojection, the
    transform for windowing, the path for log messages). The previous
    inline notebook helper had the same shape.
    """
    tiff = find_response(scene_dir)
    with rasterio.open(tiff) as src:
        arr   = src.read()
        descs = list(src.descriptions or
                     [f"band{i+1}" for i in range(src.count)])
        prof  = src.profile.copy()
        bbox  = src.bounds
        xform = src.transform
        crs   = src.crs
    return arr, descs, prof, bbox, xform, crs, tiff


def read_userdata(scene_dir):
    """Read the ``userdata.json`` sidecar a fetched scene carries.

    Returns ``None`` if absent. The fetcher writes this file for every
    scene with provenance metadata (mission, date, cloud cover, tile id,
    provider, collection, etc.). Caller is expected to handle ``None``
    when a scene was hand-built without the helper.
    """
    p = os.path.join(str(scene_dir), "userdata.json")
    if not os.path.exists(p):
        return None
    with open(p) as f:
        return json.load(f)


def print_response_summary(arr, descs, prof, bbox, xform, crs, tiff,
                           base=None) -> None:
    """Print a concise one-screen summary of a fetched scene.

    Layout: file, CRS + pixel size + extent, then per-band min/max/mean
    and NaN fraction. Matches the inline helper that grew in the tour
    notebook so a reader's eye finds the same fields in the same
    columns.

    Parameters
    ----------
    arr, descs, prof, bbox, xform, crs, tiff
        The seven values returned by :func:`open_response`.
    base : path-like, optional
        Path the ``file`` line is relative to. When ``None`` (the
        default), prints the absolute path. The notebooks pass
        their per-notebook ``OUT`` folder to get short relative paths.
    """
    px_x, px_y = xform.a, -xform.e   # transform.e is negative for north-up
    if base is not None:
        try:
            file_print = os.path.relpath(tiff, base)
        except ValueError:
            file_print = tiff
    else:
        file_print = tiff
    print(f"file       : {file_print}")
    print(f"bands      : {len(descs)}  ->  {descs}")
    print(f"shape (C,H,W) = {arr.shape}   dtype={arr.dtype}")
    print(f"CRS        : {crs}")
    print(f"pixel size : {px_x:g} x {px_y:g} (CRS units, usually metres)")
    print(f"extent     : {bbox.left:.1f}, {bbox.bottom:.1f}, "
          f"{bbox.right:.1f}, {bbox.top:.1f}")
    for i, d in enumerate(descs):
        b = arr[i]
        n_total = b.size
        n_nan   = int(np.isnan(b).sum())
        finite  = np.isfinite(b)
        if finite.any():
            v = b[finite]
            print(f"{d:>14s}  min={v.min():9.3f}  max={v.max():9.3f} "
                  f"mean={v.mean():9.3f}  NaN={100*n_nan/n_total:5.1f}%")
        else:
            print(f"{d:>14s}  (all NaN)")


# ============================================================
# Stretching / normalisation
# ============================================================

def stretch01(a, lo: float = 2, hi: float = 98):
    """Per-band percentile stretch to ``[0, 1]``; NaN stays NaN.

    The percentile defaults (2 / 98) clip the brightest 2 % and darkest
    2 % of finite pixels before scaling, so a single bright cloud or a
    dark deep-water column does not collapse the visible range of the
    rest of the scene.
    """
    a = a.astype(np.float32, copy=True)
    finite = np.isfinite(a)
    if not finite.any():
        return a
    p_lo, p_hi = np.percentile(a[finite], [lo, hi])
    if p_hi <= p_lo:
        p_hi = p_lo + 1
    return np.clip((a - p_lo) / (p_hi - p_lo), 0, 1)


def joint_rgb(r, g, b, lo: float = 2, hi: float = 98):
    """Joint-percentile stretch across three bands -> ``(H, W, 3)`` RGB.

    A *joint* stretch picks one ``(p_lo, p_hi)`` range from the union of
    all three input bands and applies the same transform to each. The
    alternative -- stretching each band separately -- flattens each
    channel to the same dynamic range and destroys the relative
    brightness between B02, B03 and B04 (so water that was originally
    bluer than redder ends up grey on the screen). The joint stretch
    preserves true relative intensity so water reads blue, vegetation
    green, urban grey.

    NaN pixels are returned as white (1.0) so masked / out-of-AOI areas
    are obvious instead of vanishing into a black background.
    """
    finite = np.isfinite(r) & np.isfinite(g) & np.isfinite(b)
    if finite.any():
        v = np.concatenate([r[finite].ravel(), g[finite].ravel(),
                            b[finite].ravel()])
        p_lo, p_hi = np.percentile(v, [lo, hi])
        if p_hi <= p_lo:
            p_hi = p_lo + 1.0
        def _norm(x):
            return np.clip((x.astype(np.float32) - p_lo) / (p_hi - p_lo), 0, 1)
        rgb = np.stack([_norm(r), _norm(g), _norm(b)], axis=-1)
    else:
        rgb = np.zeros(r.shape + (3,), dtype=np.float32)
    return np.where(np.isnan(rgb), 1.0, rgb)


def downsample(a, max_dim: int = 256):
    """Cheap stride-based downsample so previews stay small.

    Picks the stride that brings the largest dimension at or below
    ``max_dim``. Works on 2-D or 3-D arrays; the leading dimensions of
    a 3-D array (channels first) are left alone, only the last two
    (H, W) are subsampled.
    """
    h, w = a.shape[-2:]
    step = max(1, max(h, w) // max_dim)
    if a.ndim == 2:
        return a[::step, ::step]
    return a[..., ::step, ::step]


# ============================================================
# Multi-panel figures
# ============================================================

def _balanced_grid(n: int, max_ncols: int = 4) -> Tuple[int, int]:
    """Pick a ``(nrows, ncols)`` grid so the last row is at least half-full.

    Examples
    --------
    >>> _balanced_grid(5)
    (2, 3)
    >>> _balanced_grid(14)
    (4, 4)
    """
    ncols = min(max_ncols, n)
    while ncols > 2 and (n % ncols) != 0 and (n % ncols) < (ncols + 1) // 2:
        ncols -= 1
    nrows = int(np.ceil(n / ncols))
    return nrows, ncols


def show_bands(arr, descs, title: str,
               cmap_per_band: Optional[Dict[str, str]] = None,
               ncols: int = 4,
               figsize: Optional[Tuple[float, float]] = None) -> None:
    """Plot every band as a small subplot in a balanced grid.

    ``_balanced_grid`` keeps the layout from looking lopsided when ``n``
    is awkward (e.g. avoids "4 in top row, 1 in bottom row" for ``n=5``).

    ``cmap_per_band`` maps band description -> matplotlib colormap name.
    Bands not listed (or mapped to ``"gray"``) get a percentile-stretched
    grayscale; bands with an explicit colormap are shown with their raw
    values so categorical maps like ESA WorldCover (``"tab20"``) display
    correctly.
    """
    import matplotlib.pyplot as plt

    n = arr.shape[0]
    nrows, ncols = _balanced_grid(n, max_ncols=ncols)
    figsize = figsize or (3.2 * ncols, 3.2 * nrows + 0.6)
    fig, axes = plt.subplots(nrows, ncols, figsize=figsize,
                             squeeze=False, constrained_layout=True)
    fig.suptitle(title, fontsize=12)
    for i in range(nrows * ncols):
        ax = axes[i // ncols][i % ncols]
        if i >= n:
            ax.axis("off"); continue
        b = arr[i]
        cm = (cmap_per_band or {}).get(descs[i], "gray")
        if cm == "gray":
            ax.imshow(stretch01(b), cmap="gray")
        else:
            ax.imshow(b, cmap=cm)
        ax.set_title(descs[i], fontsize=9)
        ax.set_xticks([]); ax.set_yticks([])
    plt.show()


def show_rgb(arr, descs, title: str,
             r_band: str = "B04", g_band: str = "B03", b_band: str = "B02",
             stretch_lo: float = 2, stretch_hi: float = 98,
             figsize: Tuple[float, float] = (7, 7)) -> None:
    """True-colour-ish RGB composite from named bands.

    Looks up ``r_band``, ``g_band``, ``b_band`` in ``descs``, builds the
    joint-percentile stretch (see :func:`joint_rgb`), and renders the
    result with a one-line title that names the band assignment.

    Silently returns if any of the three bands is missing -- a common
    case when the user fetched only a partial band list.
    """
    import matplotlib.pyplot as plt
    try:
        ri = descs.index(r_band)
        gi = descs.index(g_band)
        bi = descs.index(b_band)
    except ValueError as e:
        print(f"(RGB composite not available: missing band {e})")
        return
    rgb = joint_rgb(arr[ri], arr[gi], arr[bi], lo=stretch_lo, hi=stretch_hi)
    fig, ax = plt.subplots(figsize=figsize)
    ax.imshow(rgb)
    ax.set_title(f"{title}  (R={r_band}, G={g_band}, B={b_band})", fontsize=11)
    ax.set_xticks([]); ax.set_yticks([])
    import matplotlib.pyplot as _plt
    _plt.tight_layout()
    plt.show()


# ============================================================
# Cloud-mask decoders + the side-by-side visualiser
# ============================================================

def decode_scl(qa):
    """Decode the Sentinel-2 L2A SCL classification into a boolean mask.

    Returns ``True`` where the pixel is one of the cloud / shadow
    classes ``{3, 8, 9, 10}`` (cloud shadow, medium-prob cloud,
    high-prob cloud, thin cirrus). The classification IDs are integers
    in the SCL band; we round-then-cast in case the band has been
    interpolated up from a finer grid.
    """
    classes = np.rint(qa).astype(np.int64)
    return np.isin(classes, [3, 8, 9, 10])


def decode_bqa(qa,
               cloud_bits: Sequence[int] = (1, 3, 4)):
    """Decode the Landsat BQA / QA_PIXEL band into a boolean mask.

    The default ``cloud_bits = (1, 3, 4)`` masks pixels flagged as
    cirrus (bit 1), cloud (bit 3), or cloud shadow (bit 4) per the
    Landsat C2 L2 specification. Pass a different list to include
    snow (bit 5) or other QA categories.
    """
    qa = np.rint(qa).astype(np.int64)
    mask = np.zeros(qa.shape, dtype=bool)
    for bit in cloud_bits:
        mask |= ((qa >> bit) & 1).astype(bool)
    return mask


def plot_cloud_pair(name: str, arr, descs,
                    intensity_band: str, qa_band: str,
                    decode_qa: Callable):
    """Three-panel cloud diagnostic: imagery / raw QA / decoded mask.

    The leftmost panel renders ``intensity_band`` percentile-stretched
    so you can see what was actually captured. The middle panel shows
    the raw QA band as a categorical colour map so you can see the
    class structure. The rightmost panel shows the boolean mask
    produced by ``decode_qa(qa)`` (typically
    :func:`decode_scl` or :func:`decode_bqa`) with the percent of
    masked pixels in the title.

    Returns the decoded mask so the caller can downstream-use it
    without re-running the decoder.
    """
    import matplotlib.pyplot as plt

    bi_int = descs.index(intensity_band)
    bi_qa  = descs.index(qa_band)
    intensity = stretch01(arr[bi_int])
    qa        = arr[bi_qa]
    mask      = decode_qa(qa)
    pct = 100.0 * mask.sum() / mask.size

    fig, axes = plt.subplots(1, 3, figsize=(13, 4.2))
    axes[0].imshow(intensity, cmap="gray")
    axes[0].set_title(f"{name} — {intensity_band} (stretched)")
    axes[1].imshow(qa, cmap="tab20")
    axes[1].set_title(f"{qa_band} (raw class / bit pattern)")
    axes[2].imshow(mask, cmap="Greys_r")
    axes[2].set_title(f"Cloud/shadow mask\n({pct:.1f}% of pixels)")
    for a in axes:
        a.set_xticks([]); a.set_yticks([])
    plt.tight_layout()
    plt.show()
    return mask
