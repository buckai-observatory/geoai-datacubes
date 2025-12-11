# test_loader_v2.py
import os
import torch
from dataset_loader import create_dataloader

# === USER INPUT ===
# Update the base path to your new tiles folder
base_dir = "data/853de8cdfef01afe5935ff340561ca1e/tiles_v2"

metadata_csv = os.path.join(base_dir, "tiles_metadata.csv")
train_dir = os.path.join(base_dir, "train")

# === CHECK FILES EXIST ===
if not os.path.exists(metadata_csv):
    raise FileNotFoundError(f"❌ Metadata CSV not found at {metadata_csv}")
if not os.path.isdir(train_dir):
    raise FileNotFoundError(f"❌ Train directory not found at {train_dir}")

# === CREATE DATALOADER ===
loader, dataset = create_dataloader(
    metadata_csv=metadata_csv,
    tiles_dir=train_dir,
    batch_size=4,
    shuffle=True,
    num_workers=2,
    img_size=256
)

print(f"📊 Total tiles found: {len(dataset)}")
print(f"📂 Tile directory: {train_dir}")

# === LOOP OVER BATCHES ===
for batch_idx, (images, meta) in enumerate(loader):
    print(f"\n🖼️ Batch {batch_idx+1}:")
    print(f"  Image batch shape: {images.shape}")  # (B, C, H, W)
    print(f"  x_offsets: {meta['x_offset'][:4]}")
    print(f"  y_offsets: {meta['y_offset'][:4]}")
    print(f"  augmentations: {meta['augmentation'][:4]}")
    
    # Show one example tile
    import matplotlib.pyplot as plt
    img = images[0].permute(1, 2, 0).numpy()  # convert to (H, W, C)
    img = (img * 0.5 + 0.5).clip(0, 1)        # de-normalize for display
    plt.imshow(img)
    plt.title(f"Example Tile (Aug: {meta['augmentation'][0]})")
    plt.axis('off')
    plt.show()

    if batch_idx == 0:  # only first batch
        break

print("\n✅ DataLoader test complete.")
