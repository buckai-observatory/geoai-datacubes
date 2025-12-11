import rasterio
import matplotlib.pyplot as plt

def show_side_by_side(path1, path2, titles=("Image 1", "Image 2")):
    with rasterio.open(path1) as src1, rasterio.open(path2) as src2:
        img1, img2 = src1.read(1), src2.read(1)
        fig, axes = plt.subplots(1, 2, figsize=(10, 5))
        axes[0].imshow(img1, cmap="gray")
        axes[0].set_title(titles[0])
        axes[1].imshow(img2, cmap="gray")
        axes[1].set_title(titles[1])
        plt.show()

show_side_by_side("data/harmonized/sentinel_reproj.tif",
                  "data/harmonized/landsat_10m.tif",
                  titles=("Sentinel (10m)", "Landsat (10m)"))
