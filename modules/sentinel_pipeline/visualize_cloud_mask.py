# visualize_cloud_mask.py
import rasterio
import numpy as np
import matplotlib.pyplot as plt
import os

# --------------------------------------------------------------------
# Path to your cached Sentinel-2 image (.tiff) and (optional) SCL band
# --------------------------------------------------------------------
base_dir = "/home/jain.894/sentinel_pipeline/data/853de8cdfef01afe5935ff340561ca1e"
import glob as _g
_tiffs = sorted(_g.glob(os.path.join(base_dir, "*_full_size.tiff")))
if not _tiffs:
    raise FileNotFoundError(f"No <Mission>_full_size.tiff in {base_dir}")
tiff_path = _tiffs[0]

# If you have a Scene Classification Layer (SCL) TIFF saved separately,
# put its path here; otherwise this will just simulate a cloud mask.
scl_path = os.path.join(base_dir, "SCL.tiff")

# --------------------------------------------------------------------
# 1️⃣ Load Sentinel-2 image (Red = B04, NIR = B08)
# --------------------------------------------------------------------
with rasterio.open(tiff_path) as src:
    img = src.read()  # shape: (bands, H, W)
    img = np.transpose(img, (1, 2, 0))  # (H, W, bands)

# Use Red (B04) and NIR (B08) for NDVI
red = img[:, :, 0].astype(float)
nir = img[:, :, 1].astype(float)
ndvi = (nir - red) / (nir + red + 1e-6)

# --------------------------------------------------------------------
# 2️⃣ Load or simulate cloud mask
# --------------------------------------------------------------------
if os.path.exists(scl_path):
    with rasterio.open(scl_path) as scl_src:
        scl = scl_src.read(1)
    # Mask clouds: Sentinel-2 SCL codes 3, 8, 9, 10, 11 are cloud-related
    cloud_mask = np.isin(scl, [3, 8, 9, 10, 11])
else:
    # Simulate cloud mask (for testing): top-right 20 % = “clouds”
    h, w = ndvi.shape
    cloud_mask = np.zeros_like(ndvi, dtype=bool)
    cloud_mask[: int(h * 0.2), int(w * 0.8) :] = True

masked_ndvi = np.where(cloud_mask, np.nan, ndvi)

# --------------------------------------------------------------------
# 3️⃣ Plot results
# --------------------------------------------------------------------
fig, axes = plt.subplots(1, 3, figsize=(15, 5))
axes[0].imshow(ndvi, cmap="RdYlGn")
axes[0].set_title("Original NDVI")
axes[1].imshow(cloud_mask, cmap="gray")
axes[1].set_title("Cloud Mask (SCL or simulated)")
axes[2].imshow(masked_ndvi, cmap="RdYlGn")
axes[2].set_title("NDVI after Cloud Filtering")
for ax in axes: ax.axis("off")

plt.tight_layout()
out_path = os.path.join(base_dir, "ndvi_cloud_comparison.png")
plt.savefig(out_path, dpi=200)
plt.show()

print(f"✅ Saved visualization → {out_path}")
