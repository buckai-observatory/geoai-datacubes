# export_zarr_all.py — Zarr v3 + metadata support
import os
import json
import rasterio
import numpy as np
from tqdm import tqdm

# zarr is a heavy optional dependency that is not required for any other
# part of the package; import it lazily inside the function so users who
# don't need Zarr export (a Colab tour, for example) can still do
# `from geoai_datacubes.preprocessing import export_to_zarr` cleanly.


def export_to_zarr(tiles_dir, output_path, metadata_csv=None):
    """
    Export GeoTIFF tiles and metadata to a Zarr dataset.
    Each Zarr dataset will also include metadata.json with tile info.
    """
    import zarr           # lazy: optional dep used only on this code path
    import pandas as pd   # lazy: only needed when metadata_csv is supplied

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    root = zarr.open_group(output_path, mode="w")

    # Load metadata CSV if available
    meta_records = []
    if metadata_csv and os.path.exists(metadata_csv):
        df_meta = pd.read_csv(metadata_csv)
        meta_records = df_meta.to_dict(orient="records")
    else:
        print(f"⚠️ No metadata CSV found for {tiles_dir}")

    count = 0
    for root_dir, _, files in os.walk(tiles_dir):
        for f in tqdm(files, desc=f"Writing Zarr ({os.path.basename(tiles_dir)})"):
            if not f.lower().endswith((".tif", ".tiff")):
                continue

            tile_path = os.path.join(root_dir, f)
            try:
                with rasterio.open(tile_path) as src:
                    arr = src.read()  # (C, H, W)
                    arr = np.nan_to_num(arr, nan=0).astype(np.float32)

                    root.create_dataset(
                        name=f"tile_{count:05d}",
                        shape=arr.shape,
                        dtype=arr.dtype,
                        data=arr,
                        chunks=(1, 256, 256),
                        overwrite=True,
                    )

                    # Find metadata row (if CSV is available)
                    meta_entry = next(
                        (m for m in meta_records if m.get("filename") == f), {}
                    )
                    meta_entry["tile_name"] = f"tile_{count:05d}"
                    meta_entry["path"] = os.path.relpath(tile_path, start=os.path.dirname(output_path))
                    count += 1

                    # Save record to metadata list
                    meta_records.append(meta_entry)

            except Exception as e:
                print(f"⚠️ Skipping {f}: {e}")

    # Write metadata.json next to Zarr group
    meta_json_path = os.path.join(output_path, "metadata.json")
    with open(meta_json_path, "w") as fp:
        json.dump(meta_records, fp, indent=2)

    print(f"✅ Done: {count} tiles saved → {output_path}")
    print(f"Metadata exported → {meta_json_path}")


if __name__ == "__main__":
    base_dir = "data/853de8cdfef01afe5935ff340561ca1e/tiles_v2"

    splits = ["train", "val", "test"]
    for split in splits:
        tiles_dir = os.path.join(base_dir, split)
        metadata_csv = os.path.join(base_dir, "tiles_metadata.csv")  # global metadata
        output_path = os.path.join(base_dir, f"{split}.zarr")

        if not os.path.exists(tiles_dir):
            print(f"⚠️ Skipping {split} — folder not found: {tiles_dir}")
            continue

        print(f"\n Exporting {split} tiles → {output_path}")
        export_to_zarr(tiles_dir, output_path, metadata_csv)
