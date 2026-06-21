"""Downstream ML / DL helpers built on top of the data cubes.

Two modules so far:

* ``segmentation`` -- ``TinyUNet`` and ``WaterUNet`` for per-pixel
  semantic segmentation. The deeper ``WaterUNet`` is the architecture
  used by `notebooks/01_water_classification.ipynb`; the smaller
  ``TinyUNet`` is a no-frills starting point for sanity-check workflows.
* ``object_detection`` -- helpers for the YOLO + USBuildingFootprints
  workflow in `notebooks/02_building_detection.ipynb` (formerly nb 03):
  ``polygons_to_yolo_tiles``, ``train_yolo_detector``,
  ``validate_yolo_model``, ``box_iou``, plus a
  :class:`YOLOBuildingDetector` orchestrator.

Future additions (classification, super-resolution, ...) will land here
as sibling modules without disturbing the existing API.
"""

from .segmentation import TinyUNet, WaterUNet
from .classification import (
    harvest_pixels,
    balance_pos_neg,
    tune_threshold,
    binary_pixel_metrics,
    predict_with_threshold,
    full_metrics,
    class_filtered_indices,
    pick_class_balanced_tiles,
)
from .object_detection import (
    YOLOBuildingDetector,
    box_iou,
    draw_yolo_boxes,
    pick_tiles_with_boxes,
    polygons_to_yolo_tiles,
    train_yolo_detector,
    validate_yolo_model,
    write_yolo_data_yaml,
    yolo_lines_to_pixel_boxes,
)

__all__ = [
    # segmentation
    "TinyUNet",
    "WaterUNet",
    # classification (pixel-level + tile-level eval)
    "harvest_pixels",
    "balance_pos_neg",
    "tune_threshold",
    "binary_pixel_metrics",
    "predict_with_threshold",
    "full_metrics",
    "class_filtered_indices",
    "pick_class_balanced_tiles",
    # object detection
    "YOLOBuildingDetector",
    "box_iou",
    "draw_yolo_boxes",
    "pick_tiles_with_boxes",
    "polygons_to_yolo_tiles",
    "train_yolo_detector",
    "validate_yolo_model",
    "write_yolo_data_yaml",
    "yolo_lines_to_pixel_boxes",
]
