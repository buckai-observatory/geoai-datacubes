"""Object-detection helpers built on top of the sentinel_pipeline data cubes.

This module promotes the recurring boilerplate from the building-detection
demo notebook (`notebooks/02_building_detection.ipynb`) into reusable
helpers so the notebook itself can stay focused on the *story* rather
than the wiring. Four buckets:

1. **Dataset assembly** -- turn a (single-scene raster, polygon ground
   truth, AOI bbox) triple into a YOLO-format dataset (image PNGs +
   label TXTs) under a chosen output directory.

2. **Visualisation** -- draw YOLO-format bounding boxes over imagery,
   and a small helper to pick tiles whose label files are non-empty
   for sanity-check panels.

3. **Training + validation** -- thin wrappers around Ultralytics'
   ``YOLO.train()`` and ``YOLO.val()`` that fix the common arguments
   so the notebook does not have to repeat them.

4. **Inference utilities** -- IoU between axis-aligned boxes and a
   YOLO-label-to-pixel-box decoder, used by the prediction-vs-truth
   panel in section 10 of the notebook.

The helpers are mission-agnostic: building-footprint detection on
NAIP is the canonical example, but anything sub-metre-or-finer with
polygon ground truth (rooftop solar panels, vehicles, parking lots,
ships, …) plugs in the same way -- you just supply a different
``polygons_utm`` GeoDataFrame.

For users who want a single-call workflow, the optional
:class:`YOLOBuildingDetector` class composes the dataset assembly,
training, and prediction-visualisation steps behind one orchestrator.
The notebook itself uses the function-level API for transparency.
"""

from __future__ import annotations

import logging
import random
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple


# ============================================================
# 1. Dataset assembly: (raster, polygons, AOI) -> YOLO dataset
# ============================================================

def _polygon_axis_bbox(geom):
    """Return ``(xmin, ymin, xmax, ymax)`` for any polygonal geometry, else None.

    Handles single-polygon, multi-polygon, and the GeometryCollection that
    can come out of ``shapely`` clip operations. Returns ``None`` for empty
    or non-polygonal inputs so the caller can simply skip the box.
    """
    if geom is None or geom.is_empty:
        return None
    if geom.geom_type == "GeometryCollection":
        from shapely.ops import unary_union
        polys = [g for g in geom.geoms
                 if g.geom_type in ("Polygon", "MultiPolygon")]
        if not polys:
            return None
        geom = unary_union(polys)
        if geom.is_empty:
            return None
    return geom.bounds


def polygons_to_yolo_tiles(
    *,
    scene_path,
    aoi_bbox_ll,
    polygons_utm,
    tile_px: int,
    image_dir,
    label_dir,
    stride: Optional[int] = None,
    pixel_size_m: float = 1.0,
    tile_basename_prefix: str = "tile",
    class_id: int = 0,
    min_box_px: int = 6,
    rgb_band_indices: Sequence[int] = (1, 2, 3),
) -> List[str]:
    """Cut ``tile_px x tile_px`` tiles from the AOI window of ``scene_path``,
    write each as a PNG into ``image_dir``, and write the matching
    YOLO-format label TXT into ``label_dir`` based on intersections with
    ``polygons_utm`` (a GeoDataFrame in the raster's CRS).

    The output layout follows the Ultralytics convention:
    ``image_dir/<basename>.png`` and ``label_dir/<basename>.txt`` with
    matching basenames per tile. Empty label files are written for tiles
    that contain no polygons -- they still belong in the dataset as
    "negative" examples.

    Parameters
    ----------
    scene_path : path-like
        Multi-band georeferenced raster (NAIP, PlanetScope, drone ortho,
        …). The first three bands of ``rgb_band_indices`` are written as
        the PNG image; alpha channels and NIR are ignored.
    aoi_bbox_ll : 4-tuple of float
        ``(lon_min, lat_min, lon_max, lat_max)`` in WGS84. The function
        crops the raster to this bbox before tiling.
    polygons_utm : geopandas.GeoDataFrame
        Ground-truth polygons in the **raster's** CRS (so the intersection
        test is exact). Caller is responsible for any prior projection.
    tile_px : int
        Tile size in pixels. 512 is a common choice for YOLO.
    image_dir, label_dir : path-like
        Output directories. Created if missing.
    stride : int, optional
        Pixel stride between tile origins. Defaults to ``tile_px`` (no
        overlap). Pass a smaller value (e.g. ``tile_px // 2``) for the
        training split to get sliding-window data augmentation.
    pixel_size_m : float
        Raster's ground sampling distance in metres per pixel. Used only
        to convert between metre-space polygon bounds and pixel-space
        bounding boxes.
    tile_basename_prefix : str
        Prefix for every tile's filename. Useful when concatenating
        multiple scenes' tiles into one split (e.g. multi-city training).
    class_id : int
        YOLO class index written into every label row. The notebook uses
        a single class (0 = "building").
    min_box_px : int
        Drop boxes whose width OR height is below this many pixels. YOLO's
        small-object detection floor is ~16 px reliable / ~6 px hard, so
        ``min_box_px=6`` is a permissive default.
    rgb_band_indices : 3-tuple of int
        Which bands of the raster to write as R, G, B. Defaults to
        ``(1, 2, 3)`` which is the convention used by both NAIP and the
        ``sentinel_pipeline`` Sentinel-2 RGB stacks.

    Returns
    -------
    list of str
        Basenames written (no extension). Useful for downstream tracking.
    """
    import numpy as np
    import rasterio
    from rasterio.warp import transform_bounds
    from shapely.geometry import box as sh_box
    from PIL import Image

    scene_path = Path(scene_path)
    image_dir = Path(image_dir); image_dir.mkdir(parents=True, exist_ok=True)
    label_dir = Path(label_dir); label_dir.mkdir(parents=True, exist_ok=True)
    if stride is None:
        stride = tile_px

    fp_sindex = polygons_utm.sindex if len(polygons_utm) > 0 else None

    with rasterio.open(scene_path) as src:
        utm_bb = transform_bounds("EPSG:4326", src.crs, *aoi_bbox_ll)
        win = rasterio.windows.from_bounds(*utm_bb, transform=src.transform)
        win = win.round_offsets().round_lengths()
        # Read the AOI sub-array once -- much faster than per-tile reads.
        arr = src.read(list(rgb_band_indices), window=win)
        arr = np.clip(arr, 0, 255).astype(np.uint8)
        win_transform = src.window_transform(win)

    H, W = arr.shape[1], arr.shape[2]
    rows = list(range(0, H - tile_px + 1, stride))
    cols = list(range(0, W - tile_px + 1, stride))
    tile_names = []

    for r in rows:
        for c in cols:
            sub = arr[:3, r:r+tile_px, c:c+tile_px]
            tile_img = np.transpose(sub, (1, 2, 0))   # (H, W, 3)

            # Tile bbox in the scene's CRS (metres).
            tile_minx = win_transform.c + c * win_transform.a
            tile_maxy = win_transform.f + r * win_transform.e   # `e` is negative
            tile_maxx = tile_minx + tile_px * win_transform.a
            tile_miny = tile_maxy + tile_px * win_transform.e
            tile_poly = sh_box(
                min(tile_minx, tile_maxx), min(tile_miny, tile_maxy),
                max(tile_minx, tile_maxx), max(tile_miny, tile_maxy),
            )

            lines = []
            if fp_sindex is not None:
                for idx in fp_sindex.intersection(tile_poly.bounds):
                    geom = polygons_utm.geometry.iloc[idx]
                    inter = geom.intersection(tile_poly)
                    bb = _polygon_axis_bbox(inter)
                    if bb is None:
                        continue
                    minx, miny, maxx, maxy = bb
                    # Polygon bounds (metres) -> pixel coords inside the tile.
                    # Image origin is at the TOP so the y axis flips.
                    x0 = (minx - tile_poly.bounds[0]) / pixel_size_m
                    x1 = (maxx - tile_poly.bounds[0]) / pixel_size_m
                    y0 = (tile_poly.bounds[3] - maxy) / pixel_size_m
                    y1 = (tile_poly.bounds[3] - miny) / pixel_size_m
                    if (x1 - x0) < min_box_px or (y1 - y0) < min_box_px:
                        continue
                    # Clip to tile, then normalise to YOLO's (cx, cy, w, h) / tile_px.
                    x0 = max(0.0, x0); y0 = max(0.0, y0)
                    x1 = min(float(tile_px), x1)
                    y1 = min(float(tile_px), y1)
                    cx = 0.5 * (x0 + x1) / tile_px
                    cy = 0.5 * (y0 + y1) / tile_px
                    w  = (x1 - x0) / tile_px
                    h  = (y1 - y0) / tile_px
                    if w <= 0 or h <= 0:
                        continue
                    lines.append(f"{class_id} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}")

            base = f"{tile_basename_prefix}_r{r:05d}_c{c:05d}"
            Image.fromarray(tile_img).save(image_dir / f"{base}.png")
            (label_dir / f"{base}.txt").write_text("\n".join(lines))
            tile_names.append(base)

    return tile_names


def write_yolo_data_yaml(yolo_root, class_names: Sequence[str] = ("building",)):
    """Write the ``data.yaml`` Ultralytics expects at the YOLO directory root.

    Assumes ``yolo_root`` already contains ``images/{train,val,test}`` and
    ``labels/{train,val,test}`` subfolders produced by
    :func:`polygons_to_yolo_tiles`.
    """
    yolo_root = Path(yolo_root)
    data_yaml = yolo_root / "data.yaml"
    names_block = "\n".join(f"  {i}: {n}" for i, n in enumerate(class_names))
    data_yaml.write_text(
        f"path: {yolo_root.resolve()}\n"
        "train: images/train\n"
        "val:   images/val\n"
        "test:  images/test\n"
        f"names:\n{names_block}\n"
    )
    return data_yaml


# ============================================================
# 2. Visualisation: draw YOLO boxes over imagery
# ============================================================

def draw_yolo_boxes(ax, img, lbl_path, color="lime", linewidth=1.5) -> int:
    """Overlay YOLO-format bounding boxes from ``lbl_path`` onto ``img``.

    The label file is expected to be the standard YOLO format -- one row
    per box: ``<class> <cx> <cy> <w> <h>`` with all coordinates normalised
    to [0, 1] relative to the image dimensions. Returns the number of
    boxes drawn (0 if the label file is missing or empty).
    """
    from matplotlib.patches import Rectangle
    ax.imshow(img)
    lbl_path = Path(lbl_path)
    if not lbl_path.exists():
        return 0
    H, W = img.shape[:2]
    n = 0
    for ln in lbl_path.read_text().splitlines():
        parts = ln.split()
        if len(parts) != 5:
            continue
        _cls, cx, cy, w, h = parts
        cx = float(cx) * W; cy = float(cy) * H
        w  = float(w)  * W; h  = float(h)  * H
        ax.add_patch(Rectangle((cx - w/2, cy - h/2), w, h, fill=False,
                               edgecolor=color, linewidth=linewidth))
        n += 1
    return n


def pick_tiles_with_boxes(image_dir, label_dir, k: int,
                          seed: Optional[int] = None) -> List[Path]:
    """Pick up to ``k`` tile PNGs from ``image_dir`` whose matching label
    file in ``label_dir`` is non-empty.

    Useful for ground-truth sanity panels where empty tiles would be
    uninformative. Shuffled by ``seed`` for reproducibility.
    """
    image_dir = Path(image_dir); label_dir = Path(label_dir)
    pool = []
    for img in sorted(image_dir.glob("*.png")):
        lbl = label_dir / (img.stem + ".txt")
        if lbl.exists() and lbl.stat().st_size > 0:
            pool.append(img)
    rng = random.Random(seed)
    rng.shuffle(pool)
    return pool[:k]


# ============================================================
# 3. Training + validation wrappers
# ============================================================

def train_yolo_detector(
    *,
    data_yaml,
    project_dir,
    run_name: str = "building_det",
    epochs: int = 60,
    imgsz: int = 512,
    batch: int = 4,
    device: str = "cpu",
    seed: int = 42,
    weights: str = "yolov8n.pt",
    workers: int = 2,
    verbose: bool = False,
    **train_kwargs,
):
    """Run Ultralytics YOLO training with the arguments the notebook needs.

    Parameters
    ----------
    weights : str
        Starting weights file. Standard sizes ``"yolov8n.pt"`` (~3 M
        params), ``"yolov8s.pt"`` (~11 M), ``"yolov8m.pt"`` (~26 M)
        download from Ultralytics on first use and live in their cache.
    **train_kwargs
        Forwarded verbatim to ``model.train(...)``. Use this for
        per-experiment augmentation tweaks (``degrees=15.0``,
        ``scale=0.5``, ``translate=0.1``, ...) without having to add a
        new keyword for each.

    Returns ``(model, results)``. ``model`` is the trained
    ``ultralytics.YOLO`` instance (carrying the best-validation weights);
    ``results`` is Ultralytics' own training-results object.

    Outputs (checkpoints, training curves, ``results.csv``) land under
    ``project_dir / run_name``. The default ``run_name`` matches the
    notebook's expectations downstream.
    """
    from ultralytics import YOLO

    logging.getLogger("ultralytics").setLevel(logging.WARNING)
    model = YOLO(weights)
    results = model.train(
        data=str(data_yaml),
        epochs=epochs,
        imgsz=imgsz,
        batch=batch,
        workers=workers,
        device=device,
        project=str(project_dir),
        name=run_name,
        exist_ok=True,
        seed=seed,
        deterministic=True,
        verbose=verbose,
        pretrained=True,
        save=True,
        save_period=-1,        # only the last + best checkpoint
        plots=True,
        **train_kwargs,
    )
    return model, results


def validate_yolo_model(model, data_yaml, *, split: str,
                        project_dir, run_name: str,
                        imgsz: int = 512, batch: int = 4,
                        device: str = "cpu") -> Tuple[object, dict]:
    """Run Ultralytics validation on a held-out split.

    Returns ``(metrics, stats)`` where ``metrics`` is the full Ultralytics
    metrics object and ``stats`` is the four-number dict the notebook
    table displays: ``mAP50``, ``mAP50-95``, ``precision``, ``recall``.
    """
    metrics = model.val(
        data=str(data_yaml), split=split, imgsz=imgsz,
        batch=batch, device=device, verbose=False,
        project=str(project_dir), name=run_name, exist_ok=True,
    )
    stats = {
        "mAP50":     float(metrics.box.map50),
        "mAP50-95":  float(metrics.box.map),
        "precision": float(metrics.box.mp),
        "recall":    float(metrics.box.mr),
    }
    return metrics, stats


# ============================================================
# 4. Inference + IoU
# ============================================================

def box_iou(a: Tuple[float, float, float, float],
            b: Tuple[float, float, float, float]) -> float:
    """IoU between two axis-aligned boxes ``(xmin, ymin, xmax, ymax)``."""
    ix0 = max(a[0], b[0]); iy0 = max(a[1], b[1])
    ix1 = min(a[2], b[2]); iy1 = min(a[3], b[3])
    iw = max(0.0, ix1 - ix0); ih = max(0.0, iy1 - iy0)
    inter = iw * ih
    union = (a[2]-a[0]) * (a[3]-a[1]) + (b[2]-b[0]) * (b[3]-b[1]) - inter
    return inter / union if union > 0 else 0.0


def yolo_lines_to_pixel_boxes(lines: Iterable[str], H: int, W: int
                              ) -> List[Tuple[float, float, float, float]]:
    """Decode YOLO-format label rows into pixel-space ``(x0, y0, x1, y1)`` boxes.

    Useful when you have predictions in YOLO normalised coords and want
    to compare them against ground-truth boxes drawn in pixel space.
    """
    out = []
    for ln in lines:
        parts = ln.split()
        if len(parts) < 5:
            continue
        _cls, cx, cy, w, h = parts[:5]
        cx = float(cx) * W; cy = float(cy) * H
        w  = float(w)  * W; h  = float(h)  * H
        out.append((cx - w/2, cy - h/2, cx + w/2, cy + h/2))
    return out


# ============================================================
# 5. Optional orchestrator for the most common workflow
# ============================================================

class YOLOBuildingDetector:
    """One-stop wrapper for the notebook-03 workflow.

    Given a dict of cities -> ``(scene_path, aoi_bbox_ll, polygons_utm)``
    triples and a role per city (``"train"`` / ``"val"`` / ``"test"``),
    this class will build the YOLO dataset, write ``data.yaml``, train a
    detector, validate on the held-out splits, and report metrics --
    each step a single method call.

    The notebook can use this when it wants the cleanest possible
    presentation, or call the module-level functions directly when it
    wants to walk a beginner through each step explicitly. They produce
    bit-identical outputs.

    Parameters
    ----------
    cities : dict
        Mapping ``city_name -> dict(scene_path=..., aoi_bbox_ll=...,
        polygons_utm=..., role=...)`` where ``role`` is one of
        ``"train"``, ``"val"``, ``"test"``.
    yolo_root : path-like
        Directory under which ``images/{train,val,test}`` and
        ``labels/{train,val,test}`` are created.
    project_dir : path-like
        Where Ultralytics writes ``runs/<run_name>/`` (checkpoints + curves).
    tile_px, pixel_size_m, class_names, min_box_px : see
        :func:`polygons_to_yolo_tiles`.
    train_stride : int, optional
        Stride for the training split only (sliding-window augmentation).
        Defaults to ``tile_px // 2``. The val/test splits always use
        non-overlapping stride for clean metrics.
    """

    def __init__(
        self,
        cities: dict,
        *,
        yolo_root,
        project_dir,
        tile_px: int = 512,
        pixel_size_m: float = 1.0,
        class_names: Sequence[str] = ("building",),
        min_box_px: int = 6,
        train_stride: Optional[int] = None,
    ):
        self.cities = cities
        self.yolo_root = Path(yolo_root)
        self.project_dir = Path(project_dir)
        self.tile_px = tile_px
        self.pixel_size_m = pixel_size_m
        self.class_names = tuple(class_names)
        self.min_box_px = min_box_px
        self.train_stride = train_stride if train_stride is not None else tile_px // 2
        self.data_yaml = None
        self.tiles_per_split: dict = {}
        self.model = None

    def build_dataset(self) -> dict:
        """Write the YOLO dataset under ``self.yolo_root`` and the data.yaml."""
        for split in ("train", "val", "test"):
            (self.yolo_root / "images" / split).mkdir(parents=True, exist_ok=True)
            (self.yolo_root / "labels" / split).mkdir(parents=True, exist_ok=True)

        for city, spec in self.cities.items():
            split = spec["role"]
            stride = self.train_stride if split == "train" else self.tile_px
            names = polygons_to_yolo_tiles(
                scene_path=spec["scene_path"],
                aoi_bbox_ll=spec["aoi_bbox_ll"],
                polygons_utm=spec["polygons_utm"],
                tile_px=self.tile_px,
                stride=stride,
                pixel_size_m=self.pixel_size_m,
                image_dir=self.yolo_root / "images" / split,
                label_dir=self.yolo_root / "labels" / split,
                tile_basename_prefix=city,
                min_box_px=self.min_box_px,
            )
            self.tiles_per_split.setdefault(split, []).extend(names)

        self.data_yaml = write_yolo_data_yaml(self.yolo_root,
                                              class_names=self.class_names)
        return self.tiles_per_split

    def train(self, **kwargs):
        """Train the detector. Forwards kwargs to :func:`train_yolo_detector`.

        Returns the trained ``ultralytics.YOLO`` model.
        """
        if self.data_yaml is None:
            raise RuntimeError("Call build_dataset() before train().")
        self.model, _ = train_yolo_detector(
            data_yaml=self.data_yaml,
            project_dir=self.project_dir,
            **kwargs,
        )
        return self.model

    def validate(self, split: str, *, run_name: Optional[str] = None,
                 **kwargs) -> dict:
        """Validate on ``split``. Returns the 4-metric stats dict."""
        if self.model is None:
            raise RuntimeError("Call train() before validate().")
        _, stats = validate_yolo_model(
            self.model, self.data_yaml, split=split,
            project_dir=self.project_dir,
            run_name=run_name or f"{split}_metrics",
            **kwargs,
        )
        return stats
