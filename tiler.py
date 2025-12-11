# tiler.py
import os
import csv
import math
import numpy as np
import rasterio
from rasterio.windows import Window
from tqdm import tqdm
from skimage.util import random_noise
from skimage.transform import rotate
import torch


def tile_geotiff(
    input_tiff,
    output_dir,
    tile_size=256,
    stride="auto",
    add_padding=False,
    augment=False,
    output_mode="geotiff",   # "geotiff", "tensor", or "on_the_fly"
    train_val_test_split=(0.8, 0.1, 0.1)
):
    """
    Splits a large GeoTIFF into smaller tiles and optionally augments them.
    Supports:
      - Auto stride (fits image edges perfectly)
      - Padding control
      - Multiple output modes
    """

    os.makedirs(output_dir, exist_ok=True)
    metadata_path = os.path.join(output_dir, "tiles_metadata.csv")

    with rasterio.open(input_tiff) as src:
        width, height = src.width, src.height
        meta = src.meta.copy()

        # --- Automatic stride if requested ---
        if stride == "auto":
            stride = tile_size
            # Adjust stride to perfectly fit without remainder if possible
            if width % tile_size != 0 or height % tile_size != 0:
                stride = math.floor(tile_size - ((width % tile_size) / math.ceil(width / tile_size)))
            print(f"🧮 Using automatic stride = {stride}")

        # --- Padding logic ---
        if add_padding:
            pad_x = (tile_size - width % tile_size) % tile_size
            pad_y = (tile_size - height % tile_size) % tile_size
            width += pad_x
            height += pad_y
            print(f"🧱 Padding applied: ({pad_x}px, {pad_y}px)")
        else:
            print("🚫 Padding disabled — last partial tiles may be dropped.")

        # --- Train/Val/Test folders if applicable ---
        if output_mode in ["geotiff", "tensor"]:
            train_dir = os.path.join(output_dir, "train")
            val_dir = os.path.join(output_dir, "val")
            test_dir = os.path.join(output_dir, "test")
            for d in [train_dir, val_dir, test_dir]:
                os.makedirs(d, exist_ok=True)

        # --- Initialize metadata CSV ---
        with open(metadata_path, "w", newline="") as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(["filename", "x_offset", "y_offset", "width", "height", "augmentation", "split"])

        tile_id = 0
        for y in tqdm(range(0, height - tile_size + 1, stride)):
            for x in range(0, width - tile_size + 1, stride):
                window = Window(x, y, tile_size, tile_size)
                img = src.read(window=window)  # (bands, H, W)
                img = np.transpose(img, (1, 2, 0))

                # --- Skip tiles with NaN values ---
                if np.isnan(img).any():
                    continue

                # --- Random split assignment ---
                rand = np.random.rand()
                if rand < train_val_test_split[0]:
                    split = "train"
                    save_dir = train_dir
                elif rand < sum(train_val_test_split[:2]):
                    split = "val"
                    save_dir = val_dir
                else:
                    split = "test"
                    save_dir = test_dir

                base_name = f"tile_{tile_id:05d}.tif"
                tile_path = os.path.join(save_dir, base_name)

                if output_mode == "geotiff":
                    meta.update({
                        "height": tile_size,
                        "width": tile_size,
                        "transform": rasterio.windows.transform(window, src.transform)
                    })
                    with rasterio.open(tile_path, "w", **meta) as dst:
                        dst.write(np.transpose(img, (2, 0, 1)))

                elif output_mode == "tensor":
                    tensor_path = os.path.join(save_dir, base_name.replace(".tif", ".pt"))
                    torch.save(torch.tensor(img).permute(2, 0, 1).float(), tensor_path)
                    tile_path = tensor_path

                elif output_mode == "on_the_fly":
                    # Skip saving, just record metadata
                    tile_path = "in_memory"

                _write_metadata(metadata_path, os.path.basename(tile_path),
                                x, y, tile_size, tile_size, "none", split)

                # --- Augmentations ---
                if augment:
                    do_augmentations(img, save_dir, tile_id, metadata_path,
                                     x, y, tile_size, tile_size, split, output_mode)

                tile_id += 1

    print(f"✅ Done. Metadata saved → {metadata_path}")
    print(f"🧩 Total tiles created: {tile_id}")


def do_augmentations(img, save_dir, tile_id, metadata_path, x, y, w, h, split, mode):
    """Apply common augmentations and save results."""
    aug_imgs = {
        "flipH": np.fliplr(img),
        "flipV": np.flipud(img),
        "rot90": rotate(img, 90, preserve_range=True),
        "rot270": rotate(img, 270, preserve_range=True),
        "noise": random_noise(img, mode="gaussian", var=0.001)
    }

    for name, im in aug_imgs.items():
        aug_name = f"tile_{tile_id:05d}_{name}.tif"

        if mode == "geotiff":
            aug_path = os.path.join(save_dir, aug_name)
            with rasterio.open(
                aug_path, "w",
                driver="GTiff", height=im.shape[0], width=im.shape[1],
                count=im.shape[2], dtype=im.dtype
            ) as dst:
                dst.write(np.transpose(im, (2, 0, 1)))

        elif mode == "tensor":
            aug_path = os.path.join(save_dir, aug_name.replace(".tif", ".pt"))
            torch.save(torch.tensor(im).permute(2, 0, 1).float(), aug_path)

        else:
            aug_path = "in_memory"

        _write_metadata(metadata_path, os.path.basename(aug_path),
                        x, y, w, h, name, split)


def _write_metadata(csv_path, filename, x, y, w, h, aug_type, split):
    """Append metadata record."""
    with open(csv_path, "a", newline="") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow([filename, x, y, w, h, aug_type, split])
