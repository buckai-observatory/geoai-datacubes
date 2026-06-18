# fusion.py
"""
Multi-mission fusion: combine per-mission ``response.tiff`` files into a single
multi-band AI data cube on a common CRS + resolution grid.

Each band keeps its provenance via a ``<MissionTag>_<BandName>`` prefix
(e.g. ``Sentinel-2_B04``, ``Sentinel-1_VV``, ``Landsat_BQA``).

Typical use::

    from fusion import fuse_response_tiffs

    fuse_response_tiffs(
        inputs=[
            "data/Sentinel-2_2024-06-12_.../response.tiff",
            "data/Sentinel-1_2024-06-29_.../response.tiff",
            "data/Landsat_2024-09-14_.../response.tiff",
        ],
        output_path="fused/columbus_cube.tiff",
        resolution=10,        # output pixel size in meters
        dst_crs=None,         # default: CRS of the first input
        bbox_mode="intersection",   # or "union"
    )

If you want a subset of bands per input, pass tuples instead::

    inputs=[
        ("data/.../Sentinel-2.../response.tiff", ["B04", "B08"]),
        ("data/.../Sentinel-1.../response.tiff", None),       # all bands
        ("data/.../Landsat.../response.tiff",    ["B04", "B05"]),
    ]
"""
import json
import os

import numpy as np
import rasterio
from rasterio.transform import from_bounds
from rasterio.warp import Resampling, reproject, transform_bounds


# QA / classification bands MUST use nearest-neighbour resampling to preserve
# integer class values.
_NEAREST_BANDS = {"SCL", "BQA", "qa_pixel", "QA_PIXEL"}


def _resampling_for(band_name):
    return Resampling.nearest if band_name in _NEAREST_BANDS else Resampling.bilinear


def _mission_tag_from_path(path):
    """Pull the mission tag out of '<Mission>_<date>_<scene_id>' folder names."""
    folder = os.path.basename(os.path.dirname(path))
    # Folder names use '_' between fields; mission tag is the first underscore
    # group EXCEPT for "Sentinel-2-L1C" which itself contains a hyphen.
    if folder.startswith("Sentinel-2-L1C"):
        return "Sentinel-2-L1C"
    return folder.split("_")[0]


def fuse_response_tiffs(
    inputs,
    output_path,
    *,
    resolution=10,
    dst_crs=None,
    bbox_mode="intersection",
):
    """Reproject + resample selected bands from each input onto a common grid
    and write a single multi-band GeoTIFF + sidecar metadata.

    Parameters
    ----------
    inputs : list
        Each element is either a path string (use all bands) or a
        ``(path, [bands])`` tuple where ``bands`` is a list of band names
        (matching the source's band descriptions) or ``None`` for all.
    output_path : str
        Destination GeoTIFF.
    resolution : float
        Output pixel size in metres.
    dst_crs : str or rasterio.crs.CRS, optional
        Target CRS. Defaults to the CRS of the first input (typically the
        highest-resolution mission, e.g. UTM for Sentinel-2 at 10 m).
    bbox_mode : {"intersection", "union"}
        How to combine the input footprints. ``"intersection"`` (default)
        keeps only the area covered by every input -- the safe choice for
        per-pixel multi-modal models.

    Returns
    -------
    dict with keys ``bands`` (list of names), ``shape`` ``(C,H,W)``,
    ``crs``, ``transform`` for the written cube.
    """
    # Normalize inputs to a list of (path, requested_bands_or_None)
    norm = []
    for item in inputs:
        if isinstance(item, str):
            norm.append((item, None))
        else:
            norm.append((item[0], item[1]))
    if not norm:
        raise ValueError("inputs is empty")

    # Pick target CRS (default: first input's)
    if dst_crs is None:
        with rasterio.open(norm[0][0]) as src:
            dst_crs = src.crs

    # Compute combined bbox in dst_crs
    bboxes = []
    for path, _ in norm:
        with rasterio.open(path) as src:
            b = transform_bounds(src.crs, dst_crs, *src.bounds, densify_pts=21)
            bboxes.append(b)

    if bbox_mode == "intersection":
        xmin = max(b[0] for b in bboxes); ymin = max(b[1] for b in bboxes)
        xmax = min(b[2] for b in bboxes); ymax = min(b[3] for b in bboxes)
    elif bbox_mode == "union":
        xmin = min(b[0] for b in bboxes); ymin = min(b[1] for b in bboxes)
        xmax = max(b[2] for b in bboxes); ymax = max(b[3] for b in bboxes)
    else:
        raise ValueError(f"bbox_mode must be 'intersection' or 'union', got {bbox_mode!r}")

    if xmin >= xmax or ymin >= ymax:
        raise RuntimeError(
            "No spatial overlap between inputs in the target CRS. "
            "Check that the response.tiffs cover the same area."
        )

    out_w = max(1, int(np.ceil((xmax - xmin) / resolution)))
    out_h = max(1, int(np.ceil((ymax - ymin) / resolution)))
    dst_transform = from_bounds(xmin, ymin, xmax, ymax, out_w, out_h)

    print(f"🗺️ Output grid: {out_w}x{out_h} px at {resolution} m in {dst_crs} "
          f"({bbox_mode} of {len(norm)} inputs)")

    # Read each requested band, reproject, and stack
    fused_bands = []
    fused_names = []

    for path, requested_bands in norm:
        mission_tag = _mission_tag_from_path(path)
        with rasterio.open(path) as src:
            descriptions = list(src.descriptions or
                                [f"band{i+1}" for i in range(src.count)])
            descriptions = [d or f"band{i+1}" for i, d in enumerate(descriptions)]

            # Resolve requested band names to source indices
            if requested_bands is None:
                indices = list(range(src.count))
            else:
                indices = []
                for b in requested_bands:
                    if b not in descriptions:
                        raise ValueError(
                            f"Band {b!r} not in {os.path.basename(path)}; "
                            f"available: {descriptions}"
                        )
                    indices.append(descriptions.index(b))

            for i in indices:
                out = np.zeros((out_h, out_w), dtype=np.float32)
                bname = descriptions[i]
                rs = _resampling_for(bname)
                reproject(
                    source=rasterio.band(src, i + 1),
                    destination=out,
                    src_transform=src.transform,
                    src_crs=src.crs,
                    dst_transform=dst_transform,
                    dst_crs=dst_crs,
                    resampling=rs,
                )
                fused_bands.append(out)
                fused_names.append(f"{mission_tag}_{bname}")
                print(f"  ↓ {f'{mission_tag}_{bname}':<32s}  {rs.name:<8s}")

    stack = np.stack(fused_bands, axis=0)   # (C, H, W)

    out_meta = {
        "driver":    "GTiff",
        "width":     out_w,
        "height":    out_h,
        "count":     len(fused_bands),
        "dtype":     "float32",
        "crs":       dst_crs,
        "transform": dst_transform,
        "compress":  "deflate",
        "tiled":     True,
    }

    out_dir = os.path.dirname(output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with rasterio.open(output_path, "w", **out_meta) as dst:
        dst.write(stack)
        for i, name in enumerate(fused_names, start=1):
            dst.set_band_description(i, name)

    # Sidecar metadata sitting alongside the fused.tiff
    base = output_path.rsplit(".", 1)[0]
    with open(base + ".meta.json", "w") as fp:
        json.dump({
            "bands":           fused_names,
            "crs":             str(dst_crs),
            "transform":       list(dst_transform),
            "shape_chw":       [len(fused_bands), out_h, out_w],
            "resolution_m":    resolution,
            "bbox_mode":       bbox_mode,
            "sources":         [p for p, _ in norm],
        }, fp, indent=2)

    print(f"✅ Fused cube: {len(fused_names)} bands, {out_h}x{out_w} px, "
          f"saved to {output_path}")

    return {
        "bands":     fused_names,
        "shape":     (len(fused_bands), out_h, out_w),
        "crs":       dst_crs,
        "transform": dst_transform,
        "path":      output_path,
    }
