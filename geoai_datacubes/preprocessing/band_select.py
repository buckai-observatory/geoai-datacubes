"""Subset bands from a fused cube and write a clean GeoTIFF.

Designed to bridge our multi-mission fused cubes into downstream modelling
packages (e.g. ``opengeos/geoai``) that expect:

* A fixed channel count (typically 3 or 4).
* A predictable per-band value range (uint8 ``[0, 255]`` or float ``[0, 1]``).
* A clean nodata convention -- PIL-based loaders and several geoai-py
  inference paths break on float ``nan`` nodata being cast into integer
  outputs.

Two named pattern groups live in :data:`BAND_PRESETS`:

**3-band scientific triplets** -- task-meaningful spectral combinations that
slot into any RGB-shaped (3-channel) model:

* ``"ndwi"`` -- ``B03``, ``B04``, ``B08`` (encodes NDWI = (G - NIR)/(G + NIR))
* ``"nbr"`` -- ``B08``, ``B11``, ``B12`` (Normalized Burn Ratio)
* ``"ndsi"`` -- ``B03``, ``B04``, ``B11`` (Normalized Difference Snow Index)

**4-band multi-modal combos** -- pair RGB with a non-optical signal:

* ``"rgb_nir"`` -- classic NAIP-style 4-band
* ``"rgb_dem"`` -- terrain-aware vegetation (RGB + elevation)
* ``"rgb_sar_vv"`` -- all-weather optical (RGB + Sentinel-1 VV)
* ``"naip"`` -- raw NAIP 4-band (R, G, B, NIR)

Pass an explicit list to :func:`select_bands` to roll your own combination.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional, Tuple, Union

import numpy as np
import rasterio

from ..fetch.missions import MISSION_PROFILES
from .band_ops import apply_band_norm, get_band_norm, split_mission_band


BAND_PRESETS: dict[str, list[str]] = {
    # 3-band scientific triplets (Sentinel-2 L2A naming).
    "ndwi": ["Sentinel-2_B03", "Sentinel-2_B04", "Sentinel-2_B08"],
    "nbr":  ["Sentinel-2_B08", "Sentinel-2_B11", "Sentinel-2_B12"],
    "ndsi": ["Sentinel-2_B03", "Sentinel-2_B04", "Sentinel-2_B11"],
    # 4-band multi-modal combos. RGB is ordered R, G, B for the consumer's
    # convenience (most pretrained vision models expect that order).
    "rgb_nir":    ["Sentinel-2_B04", "Sentinel-2_B03", "Sentinel-2_B02", "Sentinel-2_B08"],
    "rgb_dem":    ["Sentinel-2_B04", "Sentinel-2_B03", "Sentinel-2_B02", "Copernicus-DEM_DEM"],
    "rgb_sar_vv": ["Sentinel-2_B04", "Sentinel-2_B03", "Sentinel-2_B02", "Sentinel-1_VV"],
    "naip":       ["NAIP_R", "NAIP_G", "NAIP_B", "NAIP_NIR"],
    # Water-focused 4-band combos. Keep the strongest water bands (NIR
    # absorbs heavily in water; G + R drive the NDWI numerator) and add
    # SAR (water is a near-specular reflector at C-band, so VV and VH are
    # both very dark over water).
    "ndwi_sar_vv":  ["Sentinel-2_B03", "Sentinel-2_B04", "Sentinel-2_B08", "Sentinel-1_VV"],
    "ndwi_sar_dual": ["Sentinel-2_B03", "Sentinel-2_B08", "Sentinel-1_VV", "Sentinel-1_VH"],
}


def select_bands(
    cube_path: Union[Path, str],
    output_path: Union[Path, str],
    band_names: Iterable[str],
    *,
    normalize: bool = True,
    dtype: str = "uint8",
    nodata: Optional[Union[int, float]] = None,
    percentile: Tuple[float, float] = (1.0, 99.0),
    fill_value: float = 0.0,
) -> Path:
    """Subset bands from a fused cube and write a clean GeoTIFF.

    Args:
        cube_path: Fused cube GeoTIFF (as produced by
            :func:`fuse_response_tiffs`). Band descriptions are read from
            the file's ``descriptions`` metadata; this is how we look up
            bands by their mission-prefixed name.
        output_path: Where to write the subset GeoTIFF.
        band_names: Ordered list of band descriptions to keep, e.g.
            ``["Sentinel-2_B03", "Sentinel-2_B04", "Sentinel-2_B08"]``. Use
            :data:`BAND_PRESETS` for the named task-meaningful presets.
        normalize: If True, apply each band's documented ``band_meta``
            normalisation recipe (via :func:`apply_band_norm`). Falls back
            to per-band percentile stretching when no recipe is registered.
            If False, copy raw values into the destination dtype
            (which may overflow / clip).
        dtype: Output dtype. ``"uint8"`` rescales the normalised values to
            ``[0, 255]``; ``"float32"`` leaves them in ``[0, 1]``.
        nodata: Output ``nodata`` value. ``None`` (the default) writes the
            file with no nodata metadata -- the safest setting for
            downstream tools that cast nodata into the output dtype.
        percentile: ``(lo, hi)`` percentiles for the per-band stretch
            fallback. Only used when a band has no registered
            normalisation recipe.
        fill_value: Replacement value for NaN pixels in the output, in the
            destination units (e.g. 0 for uint8, 0.0 for float32).

    Returns:
        Path to the written GeoTIFF.

    Raises:
        ValueError: If the cube has no band descriptions, or if any
            requested band is missing from the cube.
    """
    cube_path = Path(cube_path)
    output_path = Path(output_path)
    band_names = list(band_names)

    with rasterio.open(cube_path) as src:
        descs = list(src.descriptions or [])
        if not descs or not all(descs):
            raise ValueError(
                f"Cube {cube_path} has empty band descriptions; cannot "
                "select by name. Fused cubes produced by "
                "fuse_response_tiffs always carry mission+band descriptions."
            )
        missing = [n for n in band_names if n not in descs]
        if missing:
            raise ValueError(
                f"Requested band(s) {missing!r} not present in cube. "
                f"Cube has: {descs}"
            )
        indices = [descs.index(n) for n in band_names]
        # rasterio.read() is 1-indexed.
        arr = src.read([i + 1 for i in indices]).astype("float32")
        meta = src.meta.copy()

    dtype_obj = np.dtype(dtype)
    is_int = dtype_obj.kind in "ui"
    target_max = float(np.iinfo(dtype_obj).max) if is_int else 1.0

    if normalize:
        out = np.empty_like(arr, dtype="float32")
        for c, name in enumerate(band_names):
            band = arr[c]
            valid_mask = np.isfinite(band)
            if not valid_mask.any():
                out[c] = fill_value
                continue

            mission, band_short = split_mission_band(name, MISSION_PROFILES)
            recipe = None
            if mission is not None:
                try:
                    recipe = get_band_norm(band_short, mission_name=mission)
                except Exception:
                    recipe = None

            if recipe is not None:
                normalized = apply_band_norm(band, recipe)
            else:
                lo, hi = np.percentile(band[valid_mask], list(percentile))
                normalized = np.clip(
                    (band - lo) / max(hi - lo, 1e-9), 0.0, 1.0
                )

            out[c] = np.where(valid_mask, normalized * target_max, fill_value)
    else:
        out = np.nan_to_num(arr, nan=fill_value)

    out = out.astype(dtype_obj)

    meta.update(count=len(band_names), dtype=str(dtype_obj), nodata=nodata)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(output_path, "w", **meta) as dst:
        dst.write(out)
        dst.descriptions = tuple(band_names)

    return output_path


def write_label_uint8(
    label_path: Union[Path, str],
    output_path: Union[Path, str],
    *,
    nodata: Optional[int] = None,
) -> Path:
    """Re-write a single-band label GeoTIFF with a clean nodata convention.

    The companion to :func:`select_bands` for the *mask* side of a
    segmentation training set. PIL-based loaders in some downstream
    packages reject masks whose nodata is ``nan`` or whose dtype is
    not a clean integer.

    Args:
        label_path: Existing single-band label raster.
        output_path: Where to write the cleaned label.
        nodata: Output ``nodata`` value (defaults to ``None`` = no nodata).

    Returns:
        Path to the written label GeoTIFF.
    """
    label_path = Path(label_path)
    output_path = Path(output_path)

    with rasterio.open(label_path) as src:
        arr = src.read(1)
        meta = src.meta.copy()

    arr = np.where(np.isfinite(arr.astype("float32")), arr, 0).astype("uint8")
    meta.update(count=1, dtype="uint8", nodata=nodata)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(output_path, "w", **meta) as dst:
        dst.write(arr[None])

    return output_path
