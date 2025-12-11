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
