import os
import rasterio
import numpy as np
from tqdm import tqdm
import pickle

# lmdb is a heavy compiled dependency that is not required for any other
# part of the package; import it lazily so users who don't need LMDB
# export can still `from geoai_datacubes.preprocessing import ...` cleanly.

def read_tiff(path):
    """Read GeoTIFF safely (supports float32 Sentinel data)."""
    try:
        with rasterio.open(path) as src:
            img = src.read()  # (C, H, W)
            img = np.moveaxis(img, 0, -1)  # → (H, W, C)
            img = np.nan_to_num(img, nan=0)
            if np.issubdtype(img.dtype, np.floating):
                img = np.clip(img, 0, 1)
                img = (img * 65535).astype(np.uint16)
            elif img.dtype != np.uint16:
                img = img.astype(np.uint16)
        return img
    except Exception as e:
        print(f"[⚠️ Skipping] {path}: {e}")
        return None


def export_to_lmdb(tiles_dir, lmdb_path, map_size_gb=10):
    """Convert all .tif tiles in tiles_dir to LMDB."""
    import lmdb  # lazy: lmdb is an optional dependency for this path only
    print(f"Exporting from {tiles_dir} → {lmdb_path}")
    all_files = []
    for root, _, files in os.walk(tiles_dir):
        for f in files:
            if f.lower().endswith((".tif", ".tiff")):
                all_files.append(os.path.join(root, f))
    all_files.sort()

    if len(all_files) == 0:
        print(f"⚠️ No TIFF files found in {tiles_dir}")
        return

    map_size = int(map_size_gb * 1024 * 1024 * 1024)
    env = lmdb.open(lmdb_path, map_size=map_size)

    count = 0
    try:
        with env.begin(write=True) as txn:
            for i, path in enumerate(tqdm(all_files, desc=f"Writing {os.path.basename(lmdb_path)}")):
                img = read_tiff(path)
                if img is None:
                    continue
                key = f"{i:06d}".encode("ascii")
                data = pickle.dumps(img, protocol=pickle.HIGHEST_PROTOCOL)
                txn.put(key, data)
                count += 1
        print(f"✅ Done: {count} tiles saved in {lmdb_path}")
    finally:
        env.close()


if __name__ == "__main__":
    # Change base_dir as per your path
    base_dir = "data/853de8cdfef01afe5935ff340561ca1e/tiles_v2"

    splits = ["train", "val", "test"]
    for split in splits:
        tiles_dir = os.path.join(base_dir, split)
        lmdb_path = os.path.join(base_dir, f"{split}_lmdb")
        if os.path.exists(tiles_dir):
            export_to_lmdb(tiles_dir, lmdb_path)
        else:
            print(f"⚠️ Skipping {split}: directory not found")
