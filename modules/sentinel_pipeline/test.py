from dataset_loader import create_dataloader

metadata_csv = "data/853de8cdfef01afe5935ff340561ca1e/tiles/tiles_metadata.csv"
tiles_dir = "data/853de8cdfef01afe5935ff340561ca1e/tiles"

loader, dataset = create_dataloader(metadata_csv, tiles_dir, batch_size=4)

print(f"Total tiles: {len(dataset)}")

# Example batch
for batch_idx, (images, meta) in enumerate(loader):
    print(f"Batch {batch_idx+1}: {images.shape}")
    print(f"Metadata keys: {list(meta.keys())}")
    print(f"x_offsets: {meta['x_offset'][:4]}")
    print(f"augmentations: {meta['augmentation'][:4]}")
    break
