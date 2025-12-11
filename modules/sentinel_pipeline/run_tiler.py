# run_tiler.py
import os
from tiler import tile_geotiff

# Input TIFF (replace this path with your actual folder)
tiff_path = "/home/jain.894/sentinel_pipeline/data/853de8cdfef01afe5935ff340561ca1e/response.tiff"

# Output directory
output_dir = os.path.join(os.path.dirname(tiff_path), "tiles_v2")

tile_geotiff(
    input_tiff=tiff_path,
    output_dir=output_dir,
    tile_size=256,          # set your desired clip size (e.g. 128, 256, etc.)
    stride="auto",          # or 128 for overlap
    add_padding=False,      # avoid NaN tiles
    augment=True,           # enable flips, rotations, noise
    output_mode="geotiff",  # options: "geotiff", "tensor", "on_the_fly"
    train_val_test_split=(0.8, 0.1, 0.1)  # split ratios
)
