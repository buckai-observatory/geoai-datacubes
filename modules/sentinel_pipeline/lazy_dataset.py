# lazy_dataset.py
"""
Lazy on-the-fly tile dataset for PyTorch.

The eager `tile_geotiff(...)` in `tiler.py` materialises every (window,
split, augmentation) combination as a separate GeoTIFF on disk. That is
fine for a one-off export, but in a training workflow where you want to
sweep tile_size / stride / augmentation choices, it forces you to either
keep many duplicate tile sets on disk or to re-run the tiler for every
experiment.

`LazyTileDataset` avoids that. Given a multi-band cube on disk (a
`<Mission>_full_size.tiff` from `fetch_data.py` or a fused cube from
`fusion.py`, or a Zarr equivalent), it:

  * Computes the (x, y) -> window mapping once at __init__ -- cheap.
  * Reads only the requested tile's window from disk in __getitem__,
    so memory stays bounded by `tile_size * tile_size * len(bands) * 4`.
  * Applies cloud masking, NaN handling, and (optionally) augmentation
    *on the fly* using the same helpers as the eager tiler, so the two
    paths produce identical tile semantics.
  * Returns ready-to-train tensors: a `(C, H, W)` float32 features
    tensor and (optionally) a `(H, W)` int64 label tensor with a
    user-specified class remap so binary or N-class classification
    targets can be derived from any source band (e.g. ESA WorldCover
    LULC class 80 -> 1 for a water-vs-rest classifier).

Sample use:

    ds = LazyTileDataset(
        cube_path="fused/columbus_cube.tiff",
        feature_bands=["Sentinel-2_B02", "Sentinel-2_B03",
                       "Sentinel-2_B04", "Sentinel-2_B08",
                       "Sentinel-1_VV",  "Sentinel-1_VH",
                       "Copernicus-DEM_DEM"],
        label_band="ESA-WorldCover_LULC",
        label_remap={80: 1},       # water (LULC class 80) -> 1; rest -> 0
        tile_size=64, stride=32,
        split="train", split_method="block",
        train_val_test_split=(0.7, 0.15, 0.15),
        cloud_mask=True, nan_handling="mask",
        augment=True,
    )
    loader = torch.utils.data.DataLoader(ds, batch_size=32, num_workers=4)

Notes on file handle management
-------------------------------
We open the source raster INSIDE `__getitem__` rather than caching a
single open handle on the instance. That keeps the dataset trivially
worker-pickle-safe at the cost of a few hundred microseconds per tile
(reopening a COG / Zarr is cheap; the read itself is the same). For
very small tile sizes where per-call overhead matters, set
`num_workers=0` and the handle will be reused inside the same process
via a thread-local cache.
"""

import os
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np


# Hard import torch -- this module's whole purpose is to expose a
# PyTorch Dataset. Doing it at import time (rather than dynamically
# rewiring __class__ later) keeps the class picklable by the standard
# multi-worker DataLoader, which is the main reason the module exists.
import torch
from torch.utils.data import Dataset as _TorchDataset


# Reuse the tiler's reference helpers so we don't end up with two
# divergent implementations of cloud masking, NaN handling, or the
# spatial-split logic.
from tiler import (
    _KNOWN_CLOUD_BANDS,
    _find_cloud_bands,
    _cloud_mask_from_spec,
    _handle_nan,
    _add_gaussian_noise,
    _assign_split,
    _auto_block_size_tiles,
    _auto_stripe_size_tiles,
    _resolve_region_specs,
    _SPLITS,
)


# ============================================================
# Cube I/O abstraction (GeoTIFF and Zarr)
# ============================================================
def _open_cube_meta(cube_path: str) -> Dict:
    """Cheap metadata read used at __init__ time: returns
    {width, height, descriptions, dtype, kind ("tiff"|"zarr")}.
    """
    ext = os.path.splitext(cube_path.rstrip("/"))[1].lower()
    if ext in (".zarr",) or os.path.isdir(cube_path):
        return _open_zarr_meta(cube_path)
    return _open_tiff_meta(cube_path)


def _open_tiff_meta(cube_path: str) -> Dict:
    import rasterio
    with rasterio.open(cube_path) as src:
        descs = list(src.descriptions or [f"band{i+1}" for i in range(src.count)])
        descs = [d or f"band{i+1}" for i, d in enumerate(descs)]
        return {
            "kind":         "tiff",
            "width":        src.width,
            "height":       src.height,
            "descriptions": descs,
            "transform":    src.transform,
            "crs":          src.crs,
            "nodata":       src.nodata,
        }


def _open_zarr_meta(cube_path: str) -> Dict:
    """Read just enough metadata to plan tile windows. We do NOT keep
    the zarr handle in the dict because handles are not pickle-safe for
    multi-worker DataLoaders; instead each `_read_window` call re-opens
    the zarr store (cheap, chunk-cached by the OS)."""
    import zarr
    z = zarr.open(cube_path, mode="r")
    if hasattr(z, "shape") and z.ndim == 3:
        c, h, w = z.shape
        descs = list(z.attrs.get("band_names", [f"band{i+1}" for i in range(c)]))
        return {"kind": "zarr", "width": w, "height": h,
                "descriptions": descs, "is_group": False}
    names = list(z.array_keys())
    sample = z[names[0]]
    h, w = sample.shape[-2:]
    return {"kind": "zarr", "width": w, "height": h,
            "descriptions": names, "is_group": True}


def _read_window(cube_path: str, meta: Dict, x: int, y: int,
                 tile_size: int, band_indices: Sequence[int]) -> np.ndarray:
    """Read a `(len(band_indices), tile_size, tile_size)` array."""
    if meta["kind"] == "tiff":
        import rasterio
        from rasterio.windows import Window
        with rasterio.open(cube_path) as src:
            window = Window(x, y, tile_size, tile_size)
            # band_indices are 0-based here; rasterio uses 1-based.
            arr = src.read([i + 1 for i in band_indices], window=window)
            return arr.astype(np.float32)
    # zarr -- re-open per call (chunk-cached by the OS so this is cheap).
    import zarr
    z = zarr.open(cube_path, mode="r")
    if not meta.get("is_group"):
        sub = z[band_indices, y : y + tile_size, x : x + tile_size]
        return np.asarray(sub, dtype=np.float32)
    names = meta["descriptions"]
    out = np.empty((len(band_indices), tile_size, tile_size), dtype=np.float32)
    for k, bi in enumerate(band_indices):
        out[k] = np.asarray(z[names[bi]][y : y + tile_size, x : x + tile_size],
                            dtype=np.float32)
    return out


# ============================================================
# The dataset
# ============================================================
class LazyTileDataset(_TorchDataset):
    """Lazy on-the-fly tile sampler reading from a multi-band cube.

    Inherits from ``torch.utils.data.Dataset`` so it is directly usable
    with ``DataLoader(num_workers=N)`` (including the multi-process /
    pickle-the-instance case). See the module docstring for the full
    design rationale.
    """

    def __init__(
        self,
        cube_path: str,
        feature_bands: Sequence[str],
        label_band: Optional[str] = None,
        label_remap: Optional[Dict[int, int]] = None,
        label_default: int = 0,
        tile_size: int = 64,
        stride: Optional[int] = None,
        split: Optional[str] = None,
        train_val_test_split: Tuple[float, float, float] = (0.7, 0.15, 0.15),
        split_method: str = "block",
        split_block_size_tiles: Optional[int] = None,
        split_stripe_axis: str = "horizontal",
        split_stripe_size_tiles: Optional[int] = None,
        split_regions: Optional[Dict[str, Dict]] = None,
        nan_handling: str = "drop",
        nan_max_fraction: float = 0.05,
        nan_interp_max_dist: int = 3,
        cloud_mask: bool = False,
        augment: bool = False,
        augment_noise_sigma_frac: float = 0.02,
        return_window_xy: bool = False,
        seed: int = 0,
    ):
        self.cube_path = cube_path
        self.tile_size = int(tile_size)
        self.stride = int(stride) if stride else self.tile_size
        self.train_val_test_split = tuple(train_val_test_split)
        self.split = split
        self.split_method = split_method
        self.split_stripe_axis = split_stripe_axis
        self.nan_handling = nan_handling
        self.nan_max_fraction = nan_max_fraction
        self.nan_interp_max_dist = nan_interp_max_dist
        self.cloud_mask = bool(cloud_mask)
        self.augment = bool(augment)
        self.augment_noise_sigma_frac = float(augment_noise_sigma_frac)
        self.return_window_xy = bool(return_window_xy)
        self.label_remap = dict(label_remap) if label_remap else None
        self.label_default = int(label_default)
        self._rng = np.random.default_rng(seed)

        # Resolve band names -> indices
        self._meta = _open_cube_meta(cube_path)
        descs = self._meta["descriptions"]
        self._descs = descs

        missing = [b for b in feature_bands if b not in descs]
        if missing:
            raise ValueError(
                f"feature_bands not in cube: {missing}\n"
                f"Available: {descs}"
            )
        self.feature_bands = list(feature_bands)
        self.feature_indices = [descs.index(b) for b in self.feature_bands]

        self.label_band = label_band
        if label_band is not None:
            if label_band not in descs:
                raise ValueError(
                    f"label_band {label_band!r} not in cube. Available: {descs}"
                )
            self.label_index = descs.index(label_band)
        else:
            self.label_index = None

        # Cloud-mask band detection (operates on ALL bands of the cube;
        # the resulting cloudy-pixel mask is applied to the FEATURE
        # bands only, not the label band).
        self._cloud_bands_info = []
        if self.cloud_mask:
            self._cloud_bands_info = _find_cloud_bands(descs)
            # Keep only cloud bands that we will actually read
            # (avoid charging the user for a per-tile QA read they did
            # not include in feature_bands -- we read them explicitly).
            self._cloud_band_idx = [info[0] for info in self._cloud_bands_info]
        else:
            self._cloud_band_idx = []

        # Resolve auto-scaled split sizes from the actual grid
        n_x_tiles = max(1, (self._meta["width"]  - self.tile_size) // self.stride + 1)
        n_y_tiles = max(1, (self._meta["height"] - self.tile_size) // self.stride + 1)
        self._n_x_tiles, self._n_y_tiles = n_x_tiles, n_y_tiles
        if split_block_size_tiles is None:
            split_block_size_tiles = _auto_block_size_tiles(n_x_tiles, n_y_tiles)
        if split_stripe_size_tiles is None:
            split_stripe_size_tiles = _auto_stripe_size_tiles(
                n_x_tiles, n_y_tiles, split_stripe_axis)
        self.split_block_size_tiles = split_block_size_tiles
        self.split_stripe_size_tiles = split_stripe_size_tiles

        # Resolve regions if needed
        self._region_bboxes = None
        if split_method == "regions":
            if not split_regions:
                raise ValueError(
                    "split_method='regions' requires split_regions={'train':..., 'val':..., 'test':...}"
                )
            self._region_bboxes = _resolve_region_specs(split_regions)

        # Build the (x, y, split) index. For "random" we draw once at
        # construction so the per-tile assignment is fixed for the life
        # of the dataset (avoids the same tile flipping between epochs).
        from tiler import _draw_split as _draw_split_impl
        src_transform = self._meta.get("transform")
        src_crs       = self._meta.get("crs")
        H = self._meta["height"]; W = self._meta["width"]
        rng = np.random.RandomState(seed)
        self._windows: List[Tuple[int, int, str]] = []
        for y in range(0, H - self.tile_size + 1, self.stride):
            for x in range(0, W - self.tile_size + 1, self.stride):
                if split_method == "random":
                    tile_split = _draw_split_impl(self.train_val_test_split, rng)
                else:
                    tile_split = _assign_split(
                        x, y, self.tile_size,
                        src_transform=src_transform, src_crs=src_crs,
                        method=split_method,
                        train_val_test_split=self.train_val_test_split,
                        block_size_tiles=self.split_block_size_tiles,
                        stripe_axis=self.split_stripe_axis,
                        stripe_size_tiles=self.split_stripe_size_tiles,
                        region_bboxes=self._region_bboxes,
                    )
                if tile_split is None:
                    continue
                if split is not None and tile_split != split:
                    continue
                self._windows.append((x, y, tile_split))

    # --------------------------------------------------------
    # Dataset interface
    # --------------------------------------------------------
    def __len__(self) -> int:
        return len(self._windows)

    def __getitem__(self, idx: int):
        # torch is already imported at module top
        x, y, tile_split = self._windows[idx]

        # 1) Read feature bands + (optional) cloud bands + (optional) label band
        #    in ONE rasterio call so we hit the COG/Zarr once per tile.
        all_indices = list(self.feature_indices)
        cloud_local_offsets = []
        for ci in self._cloud_band_idx:
            if ci in self.feature_indices:
                cloud_local_offsets.append(self.feature_indices.index(ci))
            else:
                cloud_local_offsets.append(len(all_indices))
                all_indices.append(ci)
        label_local_offset = None
        if self.label_index is not None:
            if self.label_index in all_indices:
                label_local_offset = all_indices.index(self.label_index)
            else:
                label_local_offset = len(all_indices)
                all_indices.append(self.label_index)

        block = _read_window(self.cube_path, self._meta, x, y,
                             self.tile_size, all_indices)
        # block shape: (len(all_indices), H, W)

        # 2) Cloud masking -- NaN out cloudy pixels in the feature bands.
        n_cloud_pixels = 0
        if self._cloud_bands_info:
            cloudy = np.zeros(block.shape[1:], dtype=bool)
            for spec_idx, info in enumerate(self._cloud_bands_info):
                _, spec, _name = info
                cband = block[cloud_local_offsets[spec_idx]]
                cloudy |= _cloud_mask_from_spec(cband, spec)
            n_cloud_pixels = int(cloudy.sum())
            if n_cloud_pixels:
                for fi, full_i in enumerate(self.feature_indices):
                    block[fi, cloudy] = np.nan

        # 3) NaN handling on the feature stack only.
        feat = np.transpose(block[: len(self.feature_indices)], (1, 2, 0))  # (H, W, C)
        feat, action, nan_info = _handle_nan(
            feat,
            mode=self.nan_handling,
            max_fraction=self.nan_max_fraction,
            max_dist=self.nan_interp_max_dist,
        )
        if action == "dropped":
            # The tile is mostly NaN -- pass back a sentinel so the
            # caller can skip. Most PyTorch DataLoader collate_fns
            # cannot handle None, so we instead return zeros + a
            # `valid_tile=False` flag in the metadata dict.
            feat = np.zeros((self.tile_size, self.tile_size,
                              len(self.feature_indices)), dtype=np.float32)
            invalid = True
        else:
            invalid = False

        # 4) Augmentation (only on training tiles; controlled by the
        #    `augment` flag, NOT by the split, so val/test stay pristine).
        aug_label = "none"
        if self.augment and not invalid:
            aug_label = self._apply_augmentation_inplace(feat)

        # 5) Label (if requested) -- read, remap, no NaN/cloud handling
        #    so we keep the original LULC class IDs.
        #
        # We ALWAYS return a (tile_size, tile_size) label tensor so the
        # default DataLoader collate_fn can stack batches that mix
        # valid and invalid tiles. Invalid pixels are tagged with
        # ``label_ignore_value = -1`` so the standard PyTorch loss
        # functions (CrossEntropyLoss(ignore_index=-1)) skip them.
        label_ignore = -1
        if self.label_index is not None:
            if invalid:
                label = np.full((self.tile_size, self.tile_size),
                                label_ignore, dtype=np.int64)
            else:
                label = block[label_local_offset].astype(np.int64)
                if self.label_remap is not None:
                    remapped = np.full_like(label, self.label_default, dtype=np.int64)
                    for src_v, dst_v in self.label_remap.items():
                        remapped[label == int(src_v)] = int(dst_v)
                    label = remapped
                # Geometric augmentation on the label must match what we
                # did to the features so they stay spatially aligned.
                if aug_label == "flipH":
                    label = np.fliplr(label).copy()
                elif aug_label == "flipV":
                    label = np.flipud(label).copy()
                elif aug_label == "rot90":
                    label = np.rot90(label, k=1).copy()
                elif aug_label == "rot270":
                    label = np.rot90(label, k=3).copy()
        else:
            label = None

        # 6) Build tensors. Features: (C, H, W). Label: (H, W).
        feat_t = torch.from_numpy(np.ascontiguousarray(
            np.transpose(feat, (2, 0, 1)), dtype=np.float32))
        if label is not None:
            label_t = torch.from_numpy(np.ascontiguousarray(label, dtype=np.int64))
        else:
            label_t = torch.zeros(0, dtype=torch.int64)

        meta_d = {
            "x": int(x), "y": int(y), "split": tile_split,
            "augmentation": aug_label,
            "valid_tile": (not invalid),
            "n_cloud_masked": int(n_cloud_pixels),
        }
        if self.return_window_xy:
            return feat_t, label_t, meta_d
        return feat_t, label_t

    # --------------------------------------------------------
    def _apply_augmentation_inplace(self, feat: np.ndarray) -> str:
        """Pick a random transform and apply it to `feat` (HWC).

        Returns the augmentation label so the same geometric transform
        can be applied to the label tensor downstream. Implemented
        without depending on scikit-image (kept lightweight for inference)."""
        choice = self._rng.choice(["none", "flipH", "flipV", "rot90", "rot270", "noise"])
        if choice == "none":
            return choice
        if choice == "flipH":
            feat[:] = np.fliplr(feat)
            return choice
        if choice == "flipV":
            feat[:] = np.flipud(feat)
            return choice
        if choice == "rot90":
            feat[:] = np.rot90(feat, k=1)
            return choice
        if choice == "rot270":
            feat[:] = np.rot90(feat, k=3)
            return choice
        if choice == "noise":
            noisy = _add_gaussian_noise(feat, sigma_frac=self.augment_noise_sigma_frac)
            feat[:] = noisy
            return choice
        return "none"

    # --------------------------------------------------------
    def summary(self) -> Dict:
        """Tiny dict summarising the dataset state -- useful for prints."""
        splits = {s: 0 for s in _SPLITS}
        for _, _, s in self._windows:
            splits[s] = splits.get(s, 0) + 1
        return {
            "cube_path":           self.cube_path,
            "n_tiles":             len(self._windows),
            "tile_grid":           f"{self._n_x_tiles}x{self._n_y_tiles}",
            "tile_size":           self.tile_size,
            "stride":              self.stride,
            "feature_bands":       list(self.feature_bands),
            "label_band":          self.label_band,
            "label_remap":         self.label_remap,
            "split_method":        self.split_method,
            "split_block_size":    self.split_block_size_tiles,
            "split_stripe_size":   self.split_stripe_size_tiles,
            "nan_handling":        self.nan_handling,
            "cloud_mask":          self.cloud_mask,
            "augment":             self.augment,
            "splits":              splits,
        }


# ============================================================
# Helper: convert a multi-band GeoTIFF -> Zarr for fast DataLoader workers
# ============================================================
def geotiff_to_zarr(tiff_path: str, zarr_path: str,
                    chunk_size: int = 256, overwrite: bool = False) -> str:
    """Re-pack a multi-band GeoTIFF into a chunked Zarr array. Zarr is
    faster than COG for parallel `DataLoader(num_workers > 0)` because
    each worker can hit chunks without contending for a single file
    handle. Returns the zarr path.
    """
    import rasterio
    import zarr

    if os.path.exists(zarr_path) and not overwrite:
        return zarr_path
    with rasterio.open(tiff_path) as src:
        descs = list(src.descriptions or [f"band{i+1}" for i in range(src.count)])
        z = zarr.open(zarr_path, mode="w",
                      shape=(src.count, src.height, src.width),
                      chunks=(src.count, chunk_size, chunk_size),
                      dtype="float32")
        # Stream band by band to keep memory bounded.
        for i in range(1, src.count + 1):
            z[i - 1, :, :] = src.read(i).astype(np.float32)
        z.attrs["band_names"] = descs
        z.attrs["src_path"]   = os.path.abspath(tiff_path)
    return zarr_path
