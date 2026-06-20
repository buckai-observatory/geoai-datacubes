"""Downstream ML / DL helpers built on top of the data cubes.

Currently: object-detection plumbing used by
``notebooks/03_building_detection.ipynb``. Future additions
(classification, segmentation, super-resolution) will land here as
sibling modules without disturbing the existing API.

The object-detection module exposes function-level helpers
(:func:`polygons_to_yolo_tiles`, :func:`train_yolo_detector`, ...) for
transparency in the notebook, and an optional :class:`YOLOBuildingDetector`
orchestrator for users who want a single-call workflow.
"""

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
