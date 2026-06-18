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
    split_block_size_tiles=4,      # block side, in tiles (for split_method="block")
    split_stripe_axis="horizontal",  # for split_method="stripes"
    split_stripe_size_tiles=4,       # stripe thickness in tiles
    split_regions=None,              # for split_method="regions"
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

        # --- Initialize metadata CSV ---
        with open(metadata_path, "w", newline="") as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(["filename", "x_offset", "y_offset", "width", "height",
                             "augmentation", "split"])

        tile_id = 0
        counts = {"train": 0, "val": 0, "test": 0, "skipped_region": 0, "skipped_nan": 0}

        for y in tqdm(range(0, height - tile_size + 1, stride)):
            for x in range(0, width - tile_size + 1, stride):
                window = Window(x, y, tile_size, tile_size)
                img = src.read(window=window)         # (bands, H, W)
                img = np.transpose(img, (1, 2, 0))    # (H, W, bands)

                # Drop tiles with NaNs (e.g. tile-edge gaps after reprojection)
                if np.isnan(img).any():
                    counts["skipped_nan"] += 1
                    continue

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
                        "transform": rasterio.windows.transform(window, src.transform),
                    })
                    with rasterio.open(tile_path, "w", **meta) as dst:
                        dst.write(np.transpose(img, (2, 0, 1)))

                elif output_mode == "tensor":
                    import torch  # lazy
                    tensor_path = os.path.join(save_dir, base_name.replace(".tif", ".pt"))
                    torch.save(torch.tensor(img).permute(2, 0, 1).float(), tensor_path)
                    tile_path = tensor_path

                elif output_mode == "on_the_fly":
                    tile_path = "in_memory"

                _write_metadata(metadata_path, os.path.basename(tile_path),
                                x, y, tile_size, tile_size, "none", split)

                if augment:
                    do_augmentations(img, save_dir, tile_id, metadata_path,
                                     x, y, tile_size, tile_size, split, output_mode)

                tile_id += 1

    print(f"✅ Done. Metadata saved → {metadata_path}")
    print(f"🧩 Total tiles created: {tile_id} | split_method={split_method!r}")
    print(f"   train={counts['train']}  val={counts['val']}  test={counts['test']}"
          + (f"  skipped(outside_regions)={counts['skipped_region']}" if counts['skipped_region'] else "")
          + (f"  skipped(NaN)={counts['skipped_nan']}" if counts['skipped_nan'] else ""))


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


def _write_metadata(csv_path, filename, x, y, w, h, aug_type, split):
    """Append metadata record."""
    with open(csv_path, "a", newline="") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow([filename, x, y, w, h, aug_type, split])
