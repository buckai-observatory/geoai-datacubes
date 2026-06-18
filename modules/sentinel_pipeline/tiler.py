# tiler.py
"""
Tile a (multi-band) GeoTIFF into AI-ready patches with a configurable
train / val / test split.

Four split strategies are supported (controlled by ``split_method``):

  * ``"random"``  -- per-tile coin flip (the historical default).
                     Easiest, but causes data leakage on spatially-correlated
                     imagery: adjacent tiles often share clouds, illumination,
                     vegetation, etc., so train/test metrics overstate
                     generalization.

  * ``"block"``   (DEFAULT) -- partition the raster into K-tile x K-tile blocks
                     (e.g. 4 x 4 tiles ~= 10 km on a 10 m grid) and assign each
                     whole block to one split. Removes near-neighbour leakage
                     and is the sensible default for satellite imagery.

  * ``"stripes"`` -- like blocks but 1-D: every contiguous group of N tile rows
                     (or columns, set by ``split_stripe_axis``) goes to one split.

  * ``"regions"`` -- explicit per-split AOIs using the same spec language as
                     ``aoi.py``: bbox, shapefile, centre+side_miles, or a
                     Sentinel-2 MGRS tile around a point. Tiles whose centre
                     falls outside every region are skipped.

All deterministic methods seed their random draw with a hash of the block /
stripe index so the assignment is reproducible across runs.
"""
import os
import csv
import math
import numpy as np
import rasterio
from rasterio.windows import Window
from tqdm import tqdm

# scikit-image and torch are only needed when `augment=True` or output_mode="tensor";
# import them lazily to keep the no-augmentation path lightweight.


_SPLITS = ("train", "val", "test")


# ============================================================
# Cloud / quality masking
# ============================================================
# Bands the tiler knows how to interpret as "cloudy / shadow / cirrus" QA.
# Keys are the bare band names; the same lookup also matches descriptions like
# "Sentinel-2_SCL" or "Landsat_BQA" via suffix matching, so fused cubes work too.
#   SCL classes (Sentinel-2 L2A Scene Classification Layer):
#     3 = cloud shadow, 8 = cloud medium prob, 9 = cloud high prob, 10 = thin cirrus
#   BQA bits (Landsat C2 L2 QA_PIXEL):
#     1 = dilated cloud, 3 = cloud, 4 = cloud shadow
_KNOWN_CLOUD_BANDS = {
    "SCL":      {"kind": "scl",     "flag_values": [3, 8, 9, 10]},
    "BQA":      {"kind": "qa_bits", "flag_bits":   [1, 3, 4]},
    "qa_pixel": {"kind": "qa_bits", "flag_bits":   [1, 3, 4]},
    "QA_PIXEL": {"kind": "qa_bits", "flag_bits":   [1, 3, 4]},
}


def _find_cloud_bands(descriptions):
    """Return ``[(band_index_0based, spec, display_name), ...]`` for every cloud-QA
    band found in a list of GeoTIFF band descriptions.

    Matches both bare names (``SCL``) and mission-prefixed names from fused cubes
    (``Sentinel-2_SCL``, ``Landsat_BQA``). When multiple mission cloud bands are
    present (a fused cube with both Sentinel-2 and Landsat) all of them are
    applied -- a pixel is masked if any one flags it.
    """
    out = []
    for i, d in enumerate(descriptions or []):
        if not d:
            continue
        for key, spec in _KNOWN_CLOUD_BANDS.items():
            if d == key or d.endswith("_" + key):
                out.append((i, spec, d))
                break
    return out


def _cloud_mask_from_spec(qa_band, spec):
    """Boolean mask: True where pixel is cloud/shadow/cirrus per the given spec."""
    kind = spec.get("kind")
    if kind == "scl":
        classes = np.rint(qa_band).astype(np.int64)
        return np.isin(classes, spec["flag_values"])
    if kind == "qa_bits":
        qa = np.rint(qa_band).astype(np.int64)
        mask = np.zeros(qa.shape, dtype=bool)
        for bit in spec["flag_bits"]:
            mask |= ((qa >> bit) & 1).astype(bool)
        return mask
    raise ValueError(f"Unknown cloud-mask kind: {kind!r}")


# ============================================================
# NaN handling
# ============================================================
def _fill_nan_nearest_2d(band, max_dist=3):
    """Fill NaN pixels in a 2-D array using the nearest valid neighbour.

    Only pixels whose nearest valid neighbour is within ``max_dist`` pixels are
    filled; the rest stay NaN. Works for both continuous and categorical bands
    (categorical class IDs are preserved because we copy, not interpolate).
    Returns ``(filled_array, n_filled)``.
    """
    nan_mask = np.isnan(band)
    if not nan_mask.any():
        return band, 0
    # scipy is lazy-imported so users not running NaN-fill modes don't need it.
    from scipy.ndimage import distance_transform_edt
    dist, indices = distance_transform_edt(
        nan_mask, return_distances=True, return_indices=True,
    )
    fillable = nan_mask & (dist > 0) & (dist <= max_dist)
    n_filled = int(fillable.sum())
    if n_filled == 0:
        return band, 0
    out = band.copy()
    nearest = band[tuple(indices)]
    out[fillable] = nearest[fillable]
    return out, n_filled


def _fill_nan_nearest(img, max_dist=3):
    """Apply nearest-neighbour NaN-fill to every band of an ``(H, W, C)`` tile."""
    if img.ndim == 2:
        return _fill_nan_nearest_2d(img, max_dist)
    out = img.copy()
    total_filled = 0
    for c in range(img.shape[-1]):
        out[..., c], n = _fill_nan_nearest_2d(img[..., c], max_dist)
        total_filled += n
    return out, total_filled


def _handle_nan(img, mode, max_fraction, max_dist):
    """Apply the chosen NaN-handling policy to a tile ``(H, W, C)``.

    Returns ``(img_out, action, info)`` where ``action`` is ``"kept"`` or
    ``"dropped"`` and ``info`` is a dict with the counts. In ``"mask"`` mode
    the returned image has one extra band -- a binary validity mask -- so
    callers must update their output band count accordingly.
    """
    n_nan = int(np.isnan(img).sum())
    info = {"n_nan_before": n_nan, "n_filled": 0, "added_mask_band": False}

    if n_nan == 0:
        return img, "kept", info

    frac_nan = n_nan / img.size
    if mode == "drop":
        return img, "dropped", info
    if frac_nan > max_fraction:
        # Too many NaNs to safely fill or mask — bail out regardless of mode.
        return img, "dropped", info

    if mode == "interpolate":
        filled, n_filled = _fill_nan_nearest(img, max_dist=max_dist)
        info["n_filled"] = n_filled
        if np.isnan(filled).any():
            # Some NaNs were too far from a valid pixel to be safely filled.
            return img, "dropped", info
        return filled, "kept", info

    if mode == "mask":
        # Per-pixel validity: True where ALL bands are valid.
        pixel_valid = ~np.isnan(img).any(axis=-1)
        img_filled = np.where(np.isnan(img), 0.0, img)
        mask_chan = pixel_valid.astype(img.dtype)[..., None]
        with_mask = np.concatenate([img_filled, mask_chan], axis=-1)
        info["added_mask_band"] = True
        return with_mask, "kept", info

    raise ValueError(
        f"Unknown nan_handling {mode!r}. Use 'drop', 'interpolate', or 'mask'."
    )


# ============================================================
# Split-assignment helpers
# ============================================================
def _draw_split(ratios, rng):
    """Draw "train"/"val"/"test" from a 3-tuple of ratios using a given RNG."""
    r = rng.rand()
    if r < ratios[0]:                return "train"
    if r < ratios[0] + ratios[1]:    return "val"
    return "test"


def _assign_split(
    x, y, tile_size,
    src_transform, src_crs,
    method, train_val_test_split,
    block_size_tiles=4,
    stripe_axis="horizontal",
    stripe_size_tiles=4,
    region_bboxes=None,
):
    """Return 'train' / 'val' / 'test' / None (None means: skip this tile)."""
    if method == "random":
        return _draw_split(train_val_test_split, np.random)

    if method == "block":
        block_px = max(1, block_size_tiles) * tile_size
        bx = int(x) // block_px
        by = int(y) // block_px
        seed = hash(("block", bx, by)) & 0x7fffffff
        return _draw_split(train_val_test_split, np.random.RandomState(seed))

    if method == "stripes":
        stripe_px = max(1, stripe_size_tiles) * tile_size
        if stripe_axis == "horizontal":
            stripe_idx = int(y) // stripe_px
        elif stripe_axis == "vertical":
            stripe_idx = int(x) // stripe_px
        else:
            raise ValueError(
                f"split_stripe_axis must be 'horizontal' or 'vertical', got {stripe_axis!r}"
            )
        seed = hash(("stripe", stripe_axis, stripe_idx)) & 0x7fffffff
        return _draw_split(train_val_test_split, np.random.RandomState(seed))

    if method == "regions":
        if not region_bboxes:
            raise ValueError("split_method='regions' requires split_regions")
        # Centre of the tile in source CRS, then reprojected to WGS84.
        cx_px = x + tile_size / 2.0
        cy_px = y + tile_size / 2.0
        x_proj, y_proj = src_transform * (cx_px, cy_px)
        from rasterio.warp import transform as rio_transform
        from rasterio.crs import CRS as RioCRS
        lons, lats = rio_transform(src_crs, RioCRS.from_epsg(4326), [x_proj], [y_proj])
        lon, lat = lons[0], lats[0]
        for name in _SPLITS:
            bbox = region_bboxes.get(name)
            if bbox is None:
                continue
            if bbox[0] <= lon <= bbox[2] and bbox[1] <= lat <= bbox[3]:
                return name
        return None  # tile centre fell outside every region

    raise ValueError(
        f"Unknown split_method {method!r}. "
        f"Use 'random', 'block', 'stripes', or 'regions'."
    )


def _resolve_region_specs(spec_dict):
    """Map a ``{"train": aoi_spec, "val": ..., "test": ...}`` dict to WGS84 bboxes."""
    if not isinstance(spec_dict, dict):
        raise ValueError("split_regions must be a dict with keys 'train', 'val', 'test'")
    out = {}
    for name, spec in spec_dict.items():
        if name not in _SPLITS:
            raise ValueError(f"split_regions key {name!r} must be one of {_SPLITS}")
        if isinstance(spec, (list, tuple)) and len(spec) == 4:
            out[name] = [float(v) for v in spec]
        elif isinstance(spec, dict):
            from aoi import resolve_aoi
            out[name] = resolve_aoi(spec)
        else:
            raise ValueError(
                f"split_regions[{name!r}]: spec must be a bbox list "
                f"[lon_min, lat_min, lon_max, lat_max] or an aoi.py spec dict."
            )
    return out


# ============================================================
# Main entry point
# ============================================================
def tile_geotiff(
    input_tiff,
    output_dir,
    tile_size=256,
    stride="auto",
    add_padding=False,
    augment=False,
    output_mode="geotiff",         # "geotiff", "tensor", or "on_the_fly"
    train_val_test_split=(0.8, 0.1, 0.1),
    split_method="block",          # "random" | "block" | "stripes" | "regions"
    split_block_size_tiles=4,
    split_stripe_axis="horizontal",
    split_stripe_size_tiles=4,
    split_regions=None,
    nan_handling="drop",           # "drop" | "interpolate" | "mask"
    nan_max_fraction=0.05,         # tiles with more than this fraction NaN are dropped
    nan_interp_max_dist=3,         # nearest-neighbour fill radius, in pixels (for "interpolate")
    cloud_mask=False,              # when True, NaN-out cloudy pixels using SCL / BQA / QA_PIXEL
                                   # bands found in the input (then NaN-handling kicks in)
):
    """
    Tile a multi-band GeoTIFF into AI-ready patches with a chosen split strategy.

    Beyond the simple ``random`` per-tile coin flip, three spatially-aware
    methods are available:

      * ``block``   (default) -- whole K-tile x K-tile blocks go to one split.
                                 Removes near-neighbour leakage.
                                 Tune via ``split_block_size_tiles``.
      * ``stripes`` -- N-tile-wide rows or columns go to one split.
                       Tune via ``split_stripe_axis`` ("horizontal"/"vertical")
                       and ``split_stripe_size_tiles``.
      * ``regions`` -- explicit train/val/test AOIs (uses the same aoi.py
                       spec language as ``main.py``). Tiles outside every
                       region are skipped. Tune via ``split_regions={"train":...,
                       "val":..., "test":...}``.
    """
    # Pre-resolve region specs once (uses aoi.py) so we don't repeat work per tile.
    region_bboxes = None
    if split_method == "regions":
        if not split_regions:
            raise ValueError(
                "split_method='regions' requires split_regions="
                "{'train': aoi_spec, 'val': aoi_spec, 'test': aoi_spec}"
            )
        region_bboxes = _resolve_region_specs(split_regions)

    os.makedirs(output_dir, exist_ok=True)
    metadata_path = os.path.join(output_dir, "tiles_metadata.csv")

    with rasterio.open(input_tiff) as src:
        width, height = src.width, src.height
        meta = src.meta.copy()
        src_transform = src.transform
        src_crs = src.crs

        # --- Automatic stride if requested ---
        if stride == "auto":
            stride = tile_size
            if width % tile_size != 0 or height % tile_size != 0:
                stride = math.floor(tile_size - ((width % tile_size) / math.ceil(width / tile_size)))
            print(f"🧮 Using automatic stride = {stride}")

        # --- Padding logic ---
        if add_padding:
            pad_x = (tile_size - width % tile_size) % tile_size
            pad_y = (tile_size - height % tile_size) % tile_size
            width += pad_x
            height += pad_y
            print(f"🧱 Padding applied: ({pad_x}px, {pad_y}px)")
        else:
            print("🚫 Padding disabled — last partial tiles may be dropped.")

        # --- Train/Val/Test folders if applicable ---
        if output_mode in ("geotiff", "tensor"):
            train_dir = os.path.join(output_dir, "train")
            val_dir   = os.path.join(output_dir, "val")
            test_dir  = os.path.join(output_dir, "test")
            for d in (train_dir, val_dir, test_dir):
                os.makedirs(d, exist_ok=True)
        else:
            train_dir = val_dir = test_dir = ""

        # --- Detect cloud / QA bands once (used per tile if cloud_mask=True) ---
        cloud_bands = []
        if cloud_mask:
            cloud_bands = _find_cloud_bands(list(src.descriptions or []))
            if cloud_bands:
                names = ", ".join(b[2] for b in cloud_bands)
                print(f"☁️  cloud_mask=True: NaN-ing cloudy pixels using {names}")
            else:
                print("⚠️  cloud_mask=True but no SCL / BQA / QA_PIXEL band found in input.")

        # --- Initialize metadata CSV ---
        with open(metadata_path, "w", newline="") as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(["filename", "x_offset", "y_offset", "width", "height",
                             "augmentation", "split",
                             "n_nan_before", "n_filled", "has_mask_band",
                             "n_cloud_masked"])

        tile_id = 0
        counts = {"train": 0, "val": 0, "test": 0,
                  "skipped_region": 0, "skipped_nan": 0,
                  "filled_tiles": 0, "masked_tiles": 0,
                  "cloud_masked_pixels": 0}

        for y in tqdm(range(0, height - tile_size + 1, stride)):
            for x in range(0, width - tile_size + 1, stride):
                window = Window(x, y, tile_size, tile_size)
                img = src.read(window=window)         # (bands, H, W)
                img = np.transpose(img, (1, 2, 0)).astype(np.float32, copy=False)

                # Cloud / quality masking. We NaN-out the cloudy pixels in the
                # data bands; the QA band itself is left untouched so the user
                # can still see which pixels were masked and why.
                n_cloud_this_tile = 0
                if cloud_bands:
                    cloudy = np.zeros(img.shape[:2], dtype=bool)
                    qa_idxs = set(b[0] for b in cloud_bands)
                    for bi, spec, _ in cloud_bands:
                        cloudy |= _cloud_mask_from_spec(img[..., bi], spec)
                    n_cloud_this_tile = int(cloudy.sum())
                    if n_cloud_this_tile:
                        for ci in range(img.shape[-1]):
                            if ci in qa_idxs:
                                continue
                            img[cloudy, ci] = np.nan
                        counts["cloud_masked_pixels"] += n_cloud_this_tile

                # NaN handling: drop | interpolate (fill via nearest-neighbour) |
                # mask (keep, append validity-mask band).
                img, action, nan_info = _handle_nan(
                    img,
                    mode=nan_handling,
                    max_fraction=nan_max_fraction,
                    max_dist=nan_interp_max_dist,
                )
                if action == "dropped":
                    counts["skipped_nan"] += 1
                    continue
                if nan_info["n_filled"]:
                    counts["filled_tiles"] += 1
                if nan_info["added_mask_band"]:
                    counts["masked_tiles"] += 1

                # Decide which split this tile belongs to
                split = _assign_split(
                    x, y, tile_size,
                    src_transform=src_transform, src_crs=src_crs,
                    method=split_method,
                    train_val_test_split=train_val_test_split,
                    block_size_tiles=split_block_size_tiles,
                    stripe_axis=split_stripe_axis,
                    stripe_size_tiles=split_stripe_size_tiles,
                    region_bboxes=region_bboxes,
                )
                if split is None:
                    counts["skipped_region"] += 1
                    continue
                save_dir = {"train": train_dir, "val": val_dir, "test": test_dir}[split]
                counts[split] += 1

                base_name = f"tile_{tile_id:05d}.tif"
                tile_path = os.path.join(save_dir, base_name)

                if output_mode == "geotiff":
                    meta.update({
                        "height":    tile_size,
                        "width":     tile_size,
                        "count":     img.shape[-1],   # may be src.count + 1 in "mask" mode
                        "dtype":     "float32",       # NaN handling forces float32
                        "transform": rasterio.windows.transform(window, src.transform),
                    })
                    with rasterio.open(tile_path, "w", **meta) as dst:
                        dst.write(np.transpose(img, (2, 0, 1)))
                        # Carry the source's band descriptions onto each tile so
                        # downstream readers can identify bands by name (e.g.
                        # "Sentinel-2_B04", "Copernicus-DEM_DEM"). The extra
                        # "valid_mask" band is named when present.
                        for bi in range(1, src.count + 1):
                            d = src.descriptions[bi - 1]
                            if d:
                                dst.set_band_description(bi, d)
                        if nan_info["added_mask_band"]:
                            dst.set_band_description(img.shape[-1], "valid_mask")

                elif output_mode == "tensor":
                    import torch  # lazy
                    tensor_path = os.path.join(save_dir, base_name.replace(".tif", ".pt"))
                    torch.save(torch.tensor(img).permute(2, 0, 1).float(), tensor_path)
                    tile_path = tensor_path

                elif output_mode == "on_the_fly":
                    tile_path = "in_memory"

                _write_metadata(metadata_path, os.path.basename(tile_path),
                                x, y, tile_size, tile_size, "none", split,
                                nan_info["n_nan_before"], nan_info["n_filled"],
                                nan_info["added_mask_band"],
                                n_cloud_masked=n_cloud_this_tile)

                if augment:
                    do_augmentations(img, save_dir, tile_id, metadata_path,
                                     x, y, tile_size, tile_size, split, output_mode)

                tile_id += 1

    print(f"✅ Done. Metadata saved → {metadata_path}")
    print(f"🧩 Total tiles created: {tile_id} | split_method={split_method!r} | "
          f"nan_handling={nan_handling!r}")
    parts = [f"train={counts['train']}", f"val={counts['val']}", f"test={counts['test']}"]
    if counts["skipped_region"]: parts.append(f"skipped(regions)={counts['skipped_region']}")
    if counts["skipped_nan"]:    parts.append(f"skipped(NaN)={counts['skipped_nan']}")
    if counts["filled_tiles"]:   parts.append(f"filled={counts['filled_tiles']}")
    if counts["masked_tiles"]:   parts.append(f"masked={counts['masked_tiles']}")
    if counts["cloud_masked_pixels"]:
        parts.append(f"cloud_masked_px={counts['cloud_masked_pixels']}")
    print("   " + "  ".join(parts))


def do_augmentations(img, save_dir, tile_id, metadata_path, x, y, w, h, split, mode):
    """Apply common augmentations and save results. Requires scikit-image."""
    from skimage.util import random_noise   # lazy
    from skimage.transform import rotate    # lazy
    aug_imgs = {
        "flipH":  np.fliplr(img),
        "flipV":  np.flipud(img),
        "rot90":  rotate(img, 90,  preserve_range=True),
        "rot270": rotate(img, 270, preserve_range=True),
        "noise":  random_noise(img, mode="gaussian", var=0.001),
    }

    for name, im in aug_imgs.items():
        aug_name = f"tile_{tile_id:05d}_{name}.tif"

        if mode == "geotiff":
            aug_path = os.path.join(save_dir, aug_name)
            with rasterio.open(
                aug_path, "w",
                driver="GTiff", height=im.shape[0], width=im.shape[1],
                count=im.shape[2], dtype=im.dtype,
            ) as dst:
                dst.write(np.transpose(im, (2, 0, 1)))

        elif mode == "tensor":
            import torch  # lazy
            aug_path = os.path.join(save_dir, aug_name.replace(".tif", ".pt"))
            torch.save(torch.tensor(im).permute(2, 0, 1).float(), aug_path)

        else:
            aug_path = "in_memory"

        _write_metadata(metadata_path, os.path.basename(aug_path),
                        x, y, w, h, name, split)


def _write_metadata(csv_path, filename, x, y, w, h, aug_type, split,
                    n_nan_before=0, n_filled=0, has_mask_band=False,
                    n_cloud_masked=0):
    """Append metadata record."""
    with open(csv_path, "a", newline="") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow([filename, x, y, w, h, aug_type, split,
                         n_nan_before, n_filled, int(bool(has_mask_band)),
                         n_cloud_masked])
