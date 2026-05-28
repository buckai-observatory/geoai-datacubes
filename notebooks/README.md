# Notebooks

Example notebooks for working with the AI-ready satellite **data cubes** produced by
this repo's pipeline (`modules/sentinel_pipeline`).

## [`example_datacube_ml.ipynb`](example_datacube_ml.ipynb)

A beginner-friendly, **runnable** walkthrough of machine learning on a data cube. It:

1. Opens a sample Zarr data cube that **ships with this repo** (no download or
   credentials needed) and lists its tiles, shape, channels, and metadata.
2. Visualizes the imagery and computes **NDVI** (a vegetation index) with matplotlib.
3. Trains a tiny **PyTorch mini-U-Net** end-to-end **on CPU in under a couple of
   minutes** to predict a vegetation mask (using NDVI-thresholded *pseudo-labels*,
   so no manual labelling is required).
4. Shows how to point the notebook at **your own** cube and where to go next
   (classification, segmentation, foundation-model fine-tuning). An optional KMeans
   land-cover clustering cell is included too.

### Run it

```bash
pip install -r requirements.txt      # from the repo root
jupyter notebook notebooks/example_datacube_ml.ipynb
```

The notebook resolves paths relative to the repo root, so it works whether you launch
Jupyter from the repo root or from inside `notebooks/`.
