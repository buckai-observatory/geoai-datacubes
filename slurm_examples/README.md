# `slurm_examples/` — running `geoai-datacubes` on an HPC cluster

These two scripts are **generic, cluster-agnostic** SLURM templates. They show
the *shape* of a typical batch job; you still need to fill in placeholders
(`YOUR_ALLOCATION`, `YOUR_PARTITION`, `YOUR_EMAIL`) and adapt the environment
activation lines to whatever your cluster expects. The
[**BuckAI HPC Handbook**](https://github.com/buckai-observatory/buckai-hpc-handbook)
(also distributed as a Quarto site) covers the cluster-specific bits: which
partition names exist, how to activate `conda` correctly, where shared scratch
lives, how to request GPU nodes, and so on.

## What's here

| File | Purpose |
|---|---|
| [`single_fetch.sbatch`](single_fetch.sbatch) | One job, one mission, one AOI. Equivalent to `python main.py` but on a compute node. Good for "I just need to grab one scene." |
| [`array_fetch.sbatch`](array_fetch.sbatch) | A **SLURM job array** that fetches many (mission, time-range) combinations in parallel. The list of tuples lives in the script itself; edit it, update `--array=0-N`, and submit once. |

## Quickstart

```bash
# from the repo root
sbatch slurm_examples/single_fetch.sbatch
sbatch slurm_examples/array_fetch.sbatch

# follow progress
squeue -u $USER

# inspect logs (they land in ./logs/ next to the script)
ls logs/
```

## Before you submit — checklist

1. **Edit the SBATCH header placeholders.** Every line that says
 `YOUR_ALLOCATION`, `YOUR_PARTITION`, or `YOUR_EMAIL` must be updated.
 Your sysadmin (or the HPC Handbook) will tell you which values to use.
2. **Activate your conda env correctly.** Both scripts default to
 `source activate geoai-datacubes`, which works once `conda` is on
 `$PATH`. Many clusters require either `module load miniconda3` first
 or sourcing `conda.sh` from a custom miniconda install. The commented
 lines in each script show both patterns — uncomment the one you need.
3. **Edit `main.py`'s `USER INPUT` block** (for `single_fetch.sbatch`) or
 the `TASKS=(...)` array and `# ---- EDIT ME ----` block
 (for `array_fetch.sbatch`) to describe the data you want.
4. **Resources.** Both templates request modest resources (1 task,
 2 CPUs, 8 GB RAM, 30 min walltime). That's enough for a few-km AOI;
 for an entire MGRS tile you may need 16–32 GB RAM and an hour. Tune
 as needed.
5. **Outputs.** Each job writes its data cubes into `./data/` (relative
 to the script's submit directory). Make sure that directory is on a
 filesystem with enough free space — satellite TIFFs are a few hundred
 MB each.

## A few SLURM commands you'll want

| Command | What it does |
|---|---|
| `sbatch script.sbatch` | Submit a job. |
| `squeue -u $USER` | Show your queued/running jobs. |
| `scancel <jobid>` | Cancel a queued or running job. |
| `scancel -u $USER` | Cancel **all** of your jobs (use with care). |
| `sacct -j <jobid> --format=JobID,State,Elapsed,MaxRSS` | Post-mortem: how long did it run, how much memory did it actually use. |
| `seff <jobid>` | (When available) one-line CPU/memory efficiency report — useful for right-sizing future jobs. |

## Where this fits in the bigger picture

`main.py` is intentionally a single, linear "fetch -> preprocess -> tile -> split -> export" script.
That's deliberately friendly to batch schedulers: every job is one Python process,
its inputs are configured at the top of the script, and its outputs land in
predictable folder names. Wrapping it in SLURM (or Airflow, or `xargs -P`, or
anything else) is therefore mostly about *invocation*, not about restructuring
the pipeline.

For cluster-specific details — module names, GPU partitions, JupyterHub
URLs, `tmpfs` paths, fairshare priorities — see the
[**BuckAI HPC Handbook**](https://github.com/buckai-observatory/buckai-hpc-handbook).
