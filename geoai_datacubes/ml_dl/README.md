# `geoai_datacubes.ml_dl` — downstream ML / DL helpers

Built on top of the cubes produced by `geoai_datacubes.preprocessing`.
Currently scoped to object detection; classification, segmentation,
and super-resolution modules will land here as siblings.

## Public API

```python
from geoai_datacubes.ml_dl import (
    polygons_to_yolo_tiles,    # polygon ground truth -> YOLO tiles + labels
    write_yolo_data_yaml,      # write the Ultralytics data.yaml
    draw_yolo_boxes,           # overlay YOLO boxes on imagery (matplotlib)
    pick_tiles_with_boxes,     # filter to tiles whose label TXT is non-empty
    train_yolo_detector,       # thin Ultralytics-YOLO training wrapper
    validate_yolo_model,       # held-out split metrics (mAP50, mAP50-95, P, R)
    box_iou,                   # pixel-space IoU for axis-aligned boxes
    yolo_lines_to_pixel_boxes, # decode YOLO normalised -> pixel-space boxes
    YOLOBuildingDetector,      # optional orchestrator class
)
```

## Files

| File | What it contains |
|---|---|
| `object_detection.py` | All of the above; four buckets internally (dataset assembly, visualisation, training+validation, inference IoU + viz). Built on Ultralytics YOLO; mission-agnostic — works for any (sub-metre-or-finer raster, polygon ground truth, AOI) triple. |

## Two ways to use it

The function-level API is what `notebooks/03_building_detection.ipynb`
uses, so a tutorial reader walks through each step explicitly:

```python
polygons_to_yolo_tiles(
    scene_path=naip_scene / "NAIP_full_size.tiff",
    aoi_bbox_ll=columbus_aoi,
    polygons_utm=columbus_footprints,
    tile_px=512,
    stride=256,                     # 50% overlap for sliding-window aug
    pixel_size_m=1.0,
    image_dir=yolo_root / "images" / "train",
    label_dir=yolo_root / "labels" / "train",
    tile_basename_prefix="columbus",
)

data_yaml = write_yolo_data_yaml(yolo_root, class_names=("building",))

model, _ = train_yolo_detector(
    data_yaml=data_yaml,
    project_dir=runs_dir,
    epochs=60, imgsz=512, batch=4, device="cpu",
)

_, vstats = validate_yolo_model(model, data_yaml, split="val",
                                project_dir=runs_dir, run_name="val_metrics")
print(vstats)   # {'mAP50': ..., 'mAP50-95': ..., 'precision': ..., 'recall': ...}
```

The class-level API composes those calls behind one orchestrator for
users who want a single-call workflow:

```python
det = YOLOBuildingDetector(
    cities={
        "columbus":   {"scene_path": ..., "aoi_bbox_ll": ..., "polygons_utm": ..., "role": "train"},
        "cincinnati": {..., "role": "val"},
        "cleveland":  {..., "role": "test"},
    },
    yolo_root=yolo_root,
    project_dir=runs_dir,
)
det.build_dataset()
det.train(epochs=60)
print("val :", det.validate("val"))
print("test:", det.validate("test"))
```

Both produce bit-identical outputs. Pick whichever fits the notebook
you're writing.

## Adding a new ML / DL technique

Add a sibling file (e.g., `classification.py`, `segmentation.py`,
`super_resolution.py`) and re-export its public symbols in
`ml_dl/__init__.py`. The existing `object_detection.py` is the
template: function-level helpers for transparency in notebooks plus an
optional orchestrator class for the one-call case.

Mission-agnostic helpers are preferred — accept a fused cube and a
band-name list rather than hardcoding any particular mission. The
fused-cube format contract (see
[`preprocessing/README.md`](../preprocessing/README.md)) guarantees
that `LazyTileDataset(...)` with `feature_bands=[...]` and `label_band=...`
will work for any consumer.
