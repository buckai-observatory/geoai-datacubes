"""geoai-datacubes: AI-ready multi-mission satellite data cubes.

Three subpackages organise the end-to-end workflow:

* :mod:`geoai_datacubes.fetch` -- download raw imagery and ancillary
  layers from 15 free public missions plus commercial PlanetScope,
  with a pluggable provider router (Earth Search, Microsoft Planetary
  Computer, Sentinel Hub, Planet Orders API).
* :mod:`geoai_datacubes.preprocessing` -- turn the raw fetched layers
  into AI-ready cubes: multi-mission fusion onto a common UTM grid,
  tiling into fixed-size chips with cloud and NaN handling,
  Zarr / LMDB export, on-the-fly PyTorch sampling via
  :class:`~geoai_datacubes.preprocessing.LazyTileDataset`.
* :mod:`geoai_datacubes.ml_dl` -- downstream-task helpers (currently
  object detection on Ultralytics YOLO; classification, segmentation
  and super-resolution to follow).

See ``docs/data_layers.md`` for the per-mission bands / value-ranges /
normalisation reference.
"""

__version__ = "0.1.0"
