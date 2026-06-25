# Project structure

```text
geoai-datacubes/
├── README.md                          # 1-screen overview + Colab CTA
├── LICENSE                            # MIT
├── pyproject.toml                     # PEP 621 metadata + optional extras
├── MANIFEST.in                        # sdist trim list
├── CHANGELOG.md                       # project timeline
├── CONTRIBUTORS.md                    # contributor list
├── CONTRIBUTING.md                    # how to contribute / report issues / get help
├── CODE_OF_CONDUCT.md                 # Contributor Covenant v2.1 adoption
├── CITATION.cff                       # auto-rendered "Cite this repository" button
├── Dockerfile                         # full-env image with JupyterLab + notebooks
├── .env.example                       # copy to .env and add your keys
├── .github/workflows/                 # tests, publish (PyPI), docker (GHCR)
├── docs/
│   ├── install.md                     # the install + first-run recipe
│   ├── providers.md                   # provider trade-offs and switching recipes
│   ├── fusion.md                      # multi-mission fusion
│   ├── configuration.md               # parameter tables + pipeline scripts
│   ├── credentials.md                 # Sentinel Hub + Planet credential setup
│   ├── data_layers.md                 # 26-mission band / range / normalisation reference
│   ├── adding_a_mission.md            # how to wire a new mission profile
│   └── HPC_QUICKSTART.md              # cluster-side install + SLURM training
├── notebooks/
│   ├── README.md                      # per-notebook walkthrough
│   ├── 00_geoai_datacubes_tour.ipynb  # multi-mission tour (Colab-ready)
│   ├── 01_classification.ipynb        # end-to-end ML/DL training (Colab-ready)
│   ├── 02_building_detection.ipynb    # NAIP + YOLO building detection (Colab-ready)
│   ├── 03_with_opengeos_geoai.ipynb   # geoai-py integration demo (Colab-ready)
│   ├── benchmark_lulc_class.py        # per-class binary benchmark CLI
│   ├── lulc_leaderboard.md            # per-class results table
│   └── sample_data/                   # bundled inputs for the demo notebooks
│       ├── README.md
│       └── building_footprints_oh_3cities_5mi.gpkg
├── tests/                             # pytest unit tests (run via CI)
├── smoke-tests/                       # SLURM-or-bash per-mission integration tests
├── slurm_examples/                    # generic SBATCH templates for HPC clusters
├── paper.md                           # JOSS-format paper
├── paper.bib                          # JOSS references
└── geoai_datacubes/                   # the Python package itself
    ├── README.md                      # package overview + how to extend
    ├── main.py                        # CLI entry: edit USER INPUT, then `python -m geoai_datacubes.main`
    ├── fetch/                         # data acquisition
    │   ├── aoi.py                     # AOI helpers (bbox / shapefile / centre+miles / S2-tile)
    │   ├── missions.py                # the 26-mission registry (MISSION_PROFILES)
    │   ├── fetch_data.py              # generic STAC dispatcher + SH + Planet drivers
    │   ├── _direct_fetch.py           # direct_http path for non-STAC datasets
    │   ├── config.py                  # SH OAuth env helper
    │   ├── parallel_fetch.py          # ThreadPoolExecutor wrapper
    │   └── create_stac_catalog.py     # STAC catalog builder
    ├── preprocessing/                 # raw imagery -> AI-ready cube
    │   ├── fusion.py                  # multi-mission UTM-grid fusion
    │   ├── tiler.py                   # tile a fused cube into fixed-size chips
    │   ├── lazy_dataset.py            # on-the-fly PyTorch tile sampler
    │   ├── band_ops.py                # normalise / NDVI / cloud-mask + band_meta
    │   ├── band_select.py             # select_bands + BAND_PRESETS (opengeos/geoai bridge)
    │   ├── export_zarr.py             # GeoTIFF -> Zarr
    │   ├── export_lmdb.py             # GeoTIFF -> LMDB
    │   └── visualize_cloud_mask.py    # debug helper: cloud-mask vs imagery
    ├── ml_dl/                         # downstream ML/DL helpers
    │   ├── object_detection.py        # YOLO + polygon-ground-truth plumbing
    │   ├── classification.py
    │   └── segmentation.py
    └── viz/                           # visualisation helpers
        ├── scenes.py
        ├── splits.py
        └── tiles.py
```
