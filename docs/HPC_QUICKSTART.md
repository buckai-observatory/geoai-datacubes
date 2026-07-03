# HPC quickstart — running `geoai-datacubes` on a SLURM cluster

This is the **short tactical path** from a fresh SSH session on a SLURM
cluster (Unity, OSC, or similar) to running `geoai-datacubes` at scale.
For end-to-end conceptual depth see the BuckAI HPC handbook
(<https://buckai-observatory.org/buckai-hpc-handbook/>).

`geoai-datacubes` on HPC has three flavours of workload, in order of how
often you'll run them:

1. **Data acquisition at scale** — fetching many AOIs × missions × date
   windows. CPU-only, network-bound; the package's canonical HPC use case.
2. **Cube assembly + tiling** — fusing per-mission scenes into
   multi-band cubes and cutting them into training-ready tiles.
   CPU + memory, not GPU.
3. **Model training** — U-Net / segmentation / detection on the assembled
   cubes. GPU-friendly; one of several downstream options.

Sections 3, 4, and 5 below cover each in turn. Section 6 gives you a
mosh + tmux + `salloc` recipe for interactive sessions that survive
overnight — useful for the data-inspection notebooks, Claude Code
runs, or one-off SLURM debugging.

---

## 1. Clone the repo

```bash
ssh <cluster>                                            # your usual SSH alias -- e.g. "unity" for OSU's Unity, "owens" for OSC
cd $HOME                                                 # or wherever you keep code
git clone https://github.com/buckai-observatory/geoai-datacubes.git
cd geoai-datacubes
```

HTTPS clone needs no credentials (the repo is public). Use the
`git@github.com:buckai-observatory/geoai-datacubes.git` SSH form only
if you've registered a cluster-side public key with GitHub and plan to
`git push` from the cluster — which you usually shouldn't. The cluster
is for compute; the laptop is for commits.

If you've already cloned on a previous session, `git pull` and skip ahead.

## 2. Set up the env

The package is on PyPI (`pip install geoai-datacubes`) but on an HPC
cluster you almost always want to install the heavy native-code deps
via `conda-forge` first — it avoids the GDAL / rasterio loader-chain
breakage that pure-pip installs can hit, and gives you CUDA-tested
PyTorch builds. The single recipe below builds the full `geoai-cubes`
environment used by every notebook and every SLURM script in the repo:

```bash
mamba create -y -n geoai-cubes -c conda-forge \
    python=3.11 \
    geoai-py leafmap torchgeo omniwatermask \
    rasterio gdal pyproj shapely \
    pystac pystac-client planetary-computer \
    "pytorch>=2.0" "torchvision>=0.15" \
    zarr lmdb scikit-image pillow \
    matplotlib numpy pandas tqdm requests \
    scikit-learn xgboost ultralytics transformers \
    jupyterlab ipywidgets seaborn geopandas contextily

mamba activate geoai-cubes
pip install -e .                    # editable install of this repo
bash smoke-tests/check_env.sh       # verify (import-only check, ~3 s)
```

If you already maintain a project env from a previous project, run
`bash smoke-tests/check_env.sh` inside it first — the script prints
OK / MISS per package and suggests a single `mamba install` line for
whatever's missing.

**GPU note.** For CUDA-enabled PyTorch, add `pytorch-cuda=<version>`
to the `mamba install` line (e.g. `pytorch-cuda=12.1` — check what
your cluster's `nvidia-smi` reports as the driver's CUDA version and
pick a matching build). Some clusters additionally need `module load cuda/<version>` before Python
sees the GPU — check with `nvidia-smi` inside an interactive job. If
`torch.cuda.is_available()` reports False, the CUDA module is not
loaded correctly.

---

## 3. Data acquisition at scale (the headline use case)

The `smoke-tests/fetch_*.sh` scripts are **SLURM-or-bash compatible**:
every script has `#SBATCH` headers at the top so it runs unmodified
under either `bash` (for local test) or `sbatch` (on the cluster). Each
script fetches one mission over one AOI — the standard building block.

For a real workflow you're usually fetching several missions × several
AOIs. The two common patterns:

### 3a. One SLURM job per (mission, AOI)

Simple, parallelises trivially, easy to inspect logs:

```bash
# Loop over three cities, four missions, submit 12 independent SBATCH jobs
for city in columbus cincinnati cleveland; do
  for mission in sentinel-2 sentinel-1 copernicus-dem esa-worldcover; do
    sbatch --export=ALL,CITY=$city smoke-tests/fetch_${mission}.sh
  done
done
```

Each script writes to its own scene folder under `data/`. Total wall
clock is dominated by the slowest single fetch (usually Sentinel-1 or
NAIP), not the sum, because they run in parallel.

### 3b. One SLURM job, `fetch_many_in_parallel` inside

Use when you want to keep a single output folder tidy or share a
warm STAC-client connection:

```python
# fetch_all.py — run as `sbatch smoke-tests/_run_wrapper.sh fetch_all.py`
from geoai_datacubes.fetch import fetch_many_in_parallel, resolve_aoi

fetches = []
for city, center in CITY_CENTERS.items():
    bbox = resolve_aoi({"center": center, "side_miles": 4})
    for mission in ("Sentinel-2", "Sentinel-1", "Copernicus-DEM", "ESA-WorldCover"):
        fetches.append({
            "mission": mission,
            "bands": None,
            "time_range": ("2024-06-15", "2024-07-15"),
            "roi": bbox,
            "save_folder": f"data/{city}",
        })

fetch_many_in_parallel(fetches, max_workers=8)
```

**Cluster-side gotchas for data acquisition:**

- **STAC rate limits.** Element 84 and Planetary Computer both throttle
  aggressive parallelism. `max_workers=8` is safe; `max_workers=32` will
  start seeing 429s.
- **Disk quota on `$HOME`.** A 4-mile 3-city × 4-mission fetch is
  ~1–4 GB. On clusters where `$HOME` is small, write to `/scratch` or
  the cluster's project storage instead.
- **Compute-node internet access.** Some clusters restrict outbound
  HTTPS from compute nodes; test with `curl -sI https://api.anthropic.com`
  in an interactive `srun --pty bash` on the intended partition before
  scheduling a long fetch job.

---

## 4. Cube assembly + tiling (CPU-only)

After fetching, fuse per-mission scenes into multi-band cubes and
tile them. This is CPU-bound, memory-hungry, no GPU needed:

```bash
#!/bin/bash
#SBATCH --job-name=geoai-fuse-tile
#SBATCH --time=02:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --output=smoke-tests/logs/%x.%j.out

source $(dirname $0)/../smoke-tests/_common.sh

python - <<'PY'
from geoai_datacubes.preprocessing import fuse_response_tiffs, tile_geotiff

for city in ("columbus", "cincinnati", "cleveland"):
    fuse_response_tiffs(
        inputs=[
            f"data/{city}/Sentinel-2_.../Sentinel-2_full_size.tiff",
            f"data/{city}/Sentinel-1_.../Sentinel-1_full_size.tiff",
            f"data/{city}/Copernicus-DEM_.../Copernicus-DEM_full_size.tiff",
            f"data/{city}/ESA-WorldCover_.../ESA-WorldCover_full_size.tiff",
        ],
        output_path=f"fused/{city}_cube.tiff",
        resolution=10, bbox_mode="intersection",
    )
    tile_geotiff(
        input_path=f"fused/{city}_cube.tiff",
        output_dir=f"tiles/{city}",
        tile_size=128, stride="auto",
        train_val_test_split=(0.8, 0.1, 0.1),
        split_method="block",
        nan_handling="auto",
    )
PY
```

Memory usage scales with `resolution × AOI area`. A 10 m fused cube
over a 4-mile city box is ~150 MB at float32, comfortably in RAM.
Continental-scale ROIs or 3 m PlanetScope may need `--mem=64G` and
tiling the AOI itself into strips before fusing.

For Zarr export (recommended for cluster training where COG reads
over networked filesystems are slow) chain in
`geoai_datacubes.preprocessing.geotiff_to_zarr` after `fuse_response_tiffs`.

---

## 5. Model training (GPU-friendly)

Cubes + tiles from §4 feed straight into any of the training workflows
in the repo. The generic SBATCH template:

```bash
#!/bin/bash
#SBATCH --job-name=geoai-train
#SBATCH --partition=gpu             # your cluster's GPU partition
#SBATCH --gres=gpu:1
#SBATCH --time=04:00:00
#SBATCH --mem=32G
#SBATCH --cpus-per-task=8
#SBATCH --output=smoke-tests/logs/%x.%j.out

source $(dirname $0)/../smoke-tests/_common.sh

# Adapt the python invocation below to your training driver:
python -m geoai_datacubes.ml_dl.<your_trainer> --tiles tiles/columbus/ --epochs 100
```

Three concrete examples that ship with the repo:

- **LULC classification (U-Net) — notebook 01.** Trains an ~600 K-param
  U-Net + baselines (LR, RF, XGBoost) on a fused S2+S1+DEM cube against
  any ESA-WorldCover class. On CPU: ~25–30 min end-to-end.  On a
  single A100: a few minutes. There's no dedicated SLURM script for
  this yet; wrap the notebook's training cell (or the
  `benchmark_lulc_class.py` CLI) in the template above.
- **`opengeos/geoai` integration training — notebook 03.** SMP U-Net
  (ResNet18 backbone) via `geoai.train_segmentation_landcover`. The
  notebook's default preset runs to F1 ≈ 0.95 in ~7 min on CPU; on
  GPU the same run drops to <1 min per epoch. Same wrapping pattern.
- **YOLO building detection — notebook 02 (in development).** A
  ready-made SBATCH script exists at
  [`smoke-tests/train_yolov8s.slurm`](../smoke-tests/train_yolov8s.slurm)
  and covers the full YOLOv8s training loop. Note that notebook 02
  itself is currently a work-in-progress scaffold — the trained
  detector doesn't converge reliably on the current dataset. The SLURM
  script is still useful as a **template for any Ultralytics YOLO
  workflow** you build on `geoai-datacubes` cubes.

For all three, the same rules apply:

- Match `--cpus-per-task` to the training driver's dataloader worker count.
- Set `--time` generously first, then tighten once you know the actual
  wall clock for your model + data.
- If the first training step OOMs, halve `BATCH` (or its equivalent).
- Watch `nvidia-smi` inside `squeue -u $USER` to catch runs where torch
  fell back to CPU because of a CUDA-module mismatch.

---

## 6. Interactive sessions (mosh + tmux + salloc)

For long-running exploratory work — running notebooks headfully, using
Claude Code on a compute node, or debugging a SLURM script step by
step — you want a shell that survives your laptop sleeping, network
blips, and eventual disconnects. The canonical setup:

```bash
# from your laptop — mosh handles roaming / sleep / IP changes
mosh user@<cluster>.example.edu

# inside the mosh shell, get an interactive compute-node allocation
srun --partition=interactive --time=12:00:00 \
     --cpus-per-task=4 --mem=8G --pty bash

# inside the allocation, start tmux
tmux new -s work

# inside tmux, run whatever
jupyter lab --no-browser --ip=0.0.0.0 --port=8888    # or `claude`, or ...
```

Close your laptop. Come back next day. Reconnect via `mosh` (session
resumes automatically), `ssh` to the compute node your job is on
(`squeue -u $USER` gives you the node name), `tmux attach -t work`.
Everything's where you left it.

**Caveats:**

- The SLURM allocation itself has a wall-clock limit. When
  `--time=12:00:00` expires, the job (and everything running inside
  it) dies regardless of mosh + tmux. Request a partition with a long
  max walltime and pick a generous `--time`.
- Claude Code needs outbound HTTPS to `api.anthropic.com`; if your
  cluster restricts compute-node internet, either use a partition that
  allows it or fall back to the login node.
- If your cluster has **Open OnDemand**, the browser-based JupyterLab
  session it launches gives you the same "persists across laptop
  sleep" behaviour without any of the mosh/tmux ritual.

---

## 7. Bringing results back

`rsync` from the cluster to your laptop, once `squeue -u $USER` shows
the job is done:

```bash
# From your laptop:
rsync -avh --progress \
    <cluster>:$HOME/geoai-datacubes/data \
    ./          # or wherever you want them locally

# Or a specific subset (fused cubes only, skip the raw scene folders):
rsync -avh --progress \
    <cluster>:$HOME/geoai-datacubes/fused \
    ./
```

For very large runs, consider setting up a
[Globus endpoint](https://www.globus.org/) — most academic HPC
clusters have one (OSU-affiliated users: <https://osu.globus.org/>).
It's faster than `rsync` over ssh once the transfer sizes go north of
a few tens of GB and it's resilient to network interruption.

---

## Troubleshooting

- **`torch.cuda.is_available()` returns False inside the job** —
  `module load cuda/...` before running `python`; some clusters also
  need `module load cudnn`. Check the cluster docs for the exact
  module names.
- **Job sits in `PD` forever** — `sinfo -o "%P %a %l %D %N %C"` to see
  partition availability. If GPUs are fully booked, try a different
  partition; some clusters have a `gpu-debug` partition with a 1-hour
  limit that's almost always idle.
- **STAC fetch fails with `HTTP 429` or intermittent 5xx** — drop
  parallelism or add exponential backoff. Every provider throttles
  aggressive parallel access; the `_run_fetch.py` helper retries with
  backoff by default.
- **`AttributeError` from `ultralytics` during YOLO training** —
  usually a torch / ultralytics version drift. `mamba update -c
  conda-forge ultralytics torch` typically fixes it.
- **First training step OOMs** — halve the batch size; the headline
  mAP / IoU barely shifts for the models we ship.

---

## Related docs

- [`docs/install.md`](install.md) — the same install recipe on a
  laptop (mamba + optional-dependency extras).
- [`docs/providers.md`](providers.md) — provider trade-offs, useful
  for choosing between Earth Search and Planetary Computer at
  cluster scale.
- [`docs/HPC_RUNBOOK.md`](HPC_RUNBOOK.md) — long-form multi-mission
  cube-assembly runbook (local-only; not in the public repo).
- [`smoke-tests/README.md`](../smoke-tests/README.md) — every
  per-mission fetch script + the pipeline-smoke test that this
  quickstart's data-acquisition section is built on.
- BuckAI HPC handbook
  (<https://buckai-observatory.org/buckai-hpc-handbook/>) — the
  end-to-end "laptop → Unity → OSC" Quarto book.
