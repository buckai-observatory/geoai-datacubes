# preprocess.py
import numpy as np

def normalize_band(band):
    """
    Normalizes a band to [0, 1].
    """
    return (band - np.min(band)) / (np.max(band) - np.min(band) + 1e-6)

def compute_ndvi(red, nir):
    """
    Computes NDVI = (NIR - RED) / (NIR + RED)
    """
    return (nir - red) / (nir + red + 1e-6)


def cloud_mask(qa_band, spec):
    """
    Build a boolean cloud/shadow mask from a quality band, driven by a mission's
    ``cloud_mask`` spec (see missions.py). Returns a boolean array (True = masked)
    or None if the mission has no cloud mask.

    Two kinds are supported:
      - "scl"      Sentinel-2 Scene Classification Layer: mask where the class is
                   in ``flag_values`` (e.g. cloud/shadow/cirrus classes).
      - "qa_bits"  Landsat BQA / QA_PIXEL: mask where any of ``flag_bits`` is set
                   in the bit-packed integer (e.g. cloud, dilated cloud, shadow).
    """
    if spec is None:
        return None

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

    raise ValueError(f"Unknown cloud_mask kind: {kind!r}")
