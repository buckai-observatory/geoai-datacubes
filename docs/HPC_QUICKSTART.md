# HPC quickstart — running `geoai-datacubes` on Unity / OSC

This is the **short path** from a fresh SSH session on a SLURM cluster
(Unity, OSC, or similar) to a trained `yolov8s` building detector for
notebook 02. For end-to-end conceptual depth use the BuckAI HPC
handbook (<https://buckai-observatory.org/buckai-hpc-handbook/>);
this document is the minimum tactical recipe.

## 0. What you'll have at the end

* Repo cloned at `$HOME/geoai-datacubes/`
* A conda env with all of `requirements.txt`
* A trained checkpoint at
  `notebooks/_outputs_obj/runs/building_det_yolov8s_3cities/weights/best.pt`
* The same `best.pt` rsync'd back to your laptop where the notebook's
  section-9 cache lookup picks it up automatically

## 1. Clone the repo

```bash
ssh unity                                                # or your usual alias
cd $HOME                                                 # or wherever you keep code
git clone git@github.com:buckai-observatory/geoai-datacubes.git
cd geoai-datacubes
```

If you've already cloned it on a previous job, `git pull` and skip ahead.

## 2. Check whether your existing conda env has everything

If you already maintain a project conda env on the cluster, ask it
whether it has all of `requirements.txt`:

```bash
# Activate your env first.
conda activate <yourenv>          # or `mamba activate <yourenv>`

# Fast no-network import check (~3 seconds):
bash smoke-tests/check_env.sh
# -> prints OK / MISS per package + suggests a single mamba command to
#    install the missing ones.

# Slower version-aware check (uses pip's resolver):
bash smoke-tests/check_env.sh --pip
# -> lines starting "Would install" are the deltas you need.
```

If everything imports, jump to **§4. Submit the training job**. Otherwise
either install the missing packages into your existing env (next
section) or create a fresh env.

## 3. Set up a fresh env (only if step 2 reports anything missing)

```bash
# Create a new env named geoai with Python 3.10:
mamba create -y -n geoai python=3.10
mamba activate geoai

# Install everything from requirements.txt via conda-forge (recommended
# over pip on HPC -- avoids the libLerc / GDAL loader-chain breakage we
# hit on macOS):
mamba install -y -c conda-forge --file requirements.txt

# Verify:
bash smoke-tests/check_env.sh
```

Some clusters require you to `module load cuda` before `pytorch` will
see the GPU. Check with `nvidia-smi` inside an interactive job; if
torch reports `cuda available: False`, you need to load the right CUDA
module before submitting.

## 4. Regenerate the YOLO dataset on the cluster (or rsync it from your laptop)

The YOLO directory layout (`notebooks/_outputs_obj/yolo/images/{train,val,test}`)
needs to be on the cluster before training. Two options:

**4a. Regenerate from scratch** (cleanest, ~5 min):

```bash
# Re-execute nb 02 sections 1-6 headless. Stops after the YOLO label
# generation cell; doesn't touch the training cell.
jupyter nbconvert --to notebook --inplace --execute \
    --ExecutePreprocessor.timeout=1800 \
    notebooks/02_building_detection.ipynb
```

This (a) fetches NAIP, (b) reads the bundled footprints geopackage
that ships in the repo, (c) writes the YOLO image + label tiles, and
(d) lands at the training cell which will fall through to the cached
yolov8n baseline -- that's fine, the SLURM job in step 5 actually
trains yolov8s.

**4b. Or rsync your laptop's prebuilt layout** (skips the NAIP fetch):

```bash
# From your laptop:
rsync -avh --progress \
    notebooks/_outputs_obj/yolo \
    unity:$HOME/geoai-datacubes/notebooks/_outputs_obj/
```

Either way, after this step `notebooks/_outputs_obj/yolo/images/train/`
should have ~1000+ PNG files and the matching labels next to it.

## 5. Submit the training job

```bash
# 200 epochs is the headline experiment. ~30-60 min on an A100.
sbatch smoke-tests/train_yolov8s.slurm

# Or override the epoch count without editing the script:
sbatch --export=ALL,EPOCHS=80 smoke-tests/train_yolov8s.slurm

# Or override batch size for a smaller GPU:
sbatch --export=ALL,EPOCHS=200,BATCH=8 smoke-tests/train_yolov8s.slurm
```

Monitor with `squeue -u $USER` and `tail -f smoke-tests/logs/geoai-yolov8s.*.out`.

The SLURM script expects:

| Parameter | Default | Notes |
|---|---|---|
| `--partition` | `gpu` | Adjust to your cluster's GPU partition name (`gpu-a100`, `ampere`, ...). |
| `--gres=gpu:1` | 1 GPU | yolov8s doesn't need more than one. |
| `--time` | 4 h | Generous for 200 epochs on A100; tighten on lighter GPUs. |
| `--mem` | 32 G | Adequate for batch=16. Drop to 16 G with batch=8. |
| `--cpus-per-task` | 8 | Matches `--workers 8` in the training driver. |

## 6. Pull the checkpoint back

```bash
# From your laptop, once squeue says the job has completed:
rsync -avh --progress \
    unity:$HOME/geoai-datacubes/notebooks/_outputs_obj/runs/building_det_yolov8s_3cities \
    notebooks/_outputs_obj/runs/

# Verify locally:
ls -lh notebooks/_outputs_obj/runs/building_det_yolov8s_3cities/weights/best.pt
# -> should be ~22 MB
```

Now re-run nb 02 locally and section 9 will load the new `best.pt` from
cache; sections 10-13 will render with predictions from the
just-trained model.

## Troubleshooting

* **`torch.cuda.is_available()` returns False inside the job** —
  `module load cuda/...` before running `python`; some clusters also
  need `module load cudnn`. Check the cluster docs for the exact
  module names.
* **`AttributeError: 'Ultralytics' object has no attribute 'compile'`
  or shape-mismatch in `assign_targets`** — usually means a torch /
  ultralytics version drift. `mamba update -c conda-forge ultralytics
  torch` typically fixes it.
* **The first training step OOMs** — drop `BATCH` to 8 (or 4 on a
  T4). The headline mAP barely shifts.
* **Job sits in `PD` forever** — `sinfo -o "%P %a %l %D %N %C"` to
  see partition availability. If GPUs are fully booked, try a
  different partition; e.g. some clusters have a `gpu-debug` partition
  with a 1-hour limit that's almost always idle.

## Related docs

* `docs/HPC_RUNBOOK.md` — the long-form runbook for the Lewis-County
  multi-mission cube assembly. More about data-acquisition than
  training; references the same `smoke-tests/` patterns.
* `smoke-tests/README.md` — every per-mission fetch script + the
  pipeline-smoke test. Same SLURM-or-bash convention this training job
  uses.
* BuckAI HPC handbook
  (<https://buckai-observatory.org/buckai-hpc-handbook/>) -- the
  end-to-end "laptop → Unity → OSC" Quarto book.
