# dataset_loader.py
import os
import pandas as pd
import torch
from torch.utils.data import Dataset, DataLoader
from torchvision import transforms
from PIL import Image


class SentinelTileDataset(Dataset):
    """
    PyTorch dataset loader for tiled and augmented satellite imagery.
    Reads tiles_metadata.csv and returns (image_tensor, metadata_dict).
    """

    def __init__(self, metadata_csv, tiles_dir, transform=None):
        self.metadata = pd.read_csv(metadata_csv)
        self.tiles_dir = tiles_dir
        self.transform = transform

    def __len__(self):
        return len(self.metadata)
    
    def __getitem__(self, idx):
        row = self.metadata.iloc[idx]
        img_path = os.path.join(self.tiles_dir, row["filename"])

        import rasterio
        try:
            with rasterio.open(img_path) as src:
                image = src.read()  # (C, H, W)
                image = torch.tensor(image, dtype=torch.float32)
        except Exception as e:
            print(f"⚠️ Skipping corrupted tile: {img_path} ({e})")
            image = torch.zeros((3, 256, 256), dtype=torch.float32)

        # --- Ensure consistent 3-channel shape ---
        if image.shape[0] == 1:            # grayscale
            image = image.repeat(3, 1, 1)
        elif image.shape[0] == 2:          # VV+VH radar → add dummy band
            pad = torch.zeros_like(image[0:1])
            image = torch.cat([image, pad], dim=0)
        elif image.shape[0] > 3:           # hyperspectral, keep first 3
            image = image[:3]

        image = image / 255.0  # normalize to [0,1]

        # Convert to PIL for torchvision transforms
        from torchvision.transforms.functional import to_pil_image
        pil_img = to_pil_image(image)

        if self.transform:
            pil_img = self.transform(pil_img)

        metadata = {
            "x_offset": row["x_offset"],
            "y_offset": row["y_offset"],
            "augmentation": row["augmentation"]
        }

        return pil_img, metadata


def get_default_transforms(img_size=256, normalize=True):
    """Default preprocessing transforms."""
    t = [transforms.Resize((img_size, img_size)), transforms.ToTensor()]
    if normalize:
        t.append(transforms.Normalize(mean=[0.5, 0.5, 0.5],
                                      std=[0.5, 0.5, 0.5]))
    return transforms.Compose(t)


def create_dataloader(metadata_csv, tiles_dir, batch_size=8,
                      shuffle=True, num_workers=2, img_size=256):
    """Creates a PyTorch DataLoader with default transforms."""
    transform = get_default_transforms(img_size)
    dataset = SentinelTileDataset(metadata_csv, tiles_dir, transform)
    loader = DataLoader(dataset, batch_size=batch_size,
                        shuffle=shuffle, num_workers=num_workers)
    return loader, dataset
