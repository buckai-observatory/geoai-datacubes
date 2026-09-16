# Performance-benchmark raw records

This directory holds the raw per-run JSONL records produced by
[`smoke-tests/perf_bench.py`](../perf_bench.py). The subfolder
[`reference_2026-09-03/`](reference_2026-09-03/) contains the **exact
raw dataset** underlying the tables published at
[`docs/performance.qmd`](../../docs/performance.qmd), committed so a
third party can independently re-aggregate the min/median/max numbers
without re-running the fetch harness.

## What's in `reference_2026-09-03/`

13 JSONL files, 94 rows, gathered 2026-09-03 across two machines:

| File suffix | Machine | Runs |
|---|---|---|
| `laptop-quick*` | MacBook M-series, 10-core, 16 GB, cellular tethering, macOS 15.5, Python 3.11.15 | 3 quick runs |
| `laptop-cellular*` | Same laptop, full config sweep | 3 runs |
| `laptop-retry*` | Same laptop, re-run of three configs that had bad params in the first pass (S1-RTC lowercase bands, `3DEP-seamless` vs `3DEP`, Landsat time range) | 4 retry runs |
| `unity-cluster*` | Ohio Supercomputer Center Unity, batch partition, 32-core Xeon (4 requested), 16 GB, Linux, Python 3.12 | 3 runs |

Each row is one full fetch of one mission through one provider at one
AOI-size + resolution combination. File header row (`"kind": "header"`)
carries the machine spec; subsequent rows (`"kind": "row"`) carry
timing, output size, produced-pixel count, and any error message.

## Re-aggregating the published tables

To reproduce every table in [`docs/performance.qmd`](../../docs/performance.qmd)
from these raw records:

```bash
# Aggregate everything (both machines):
python smoke-tests/perf_bench_agg.py --out smoke-tests/perf_logs

# Just one machine at a time:
python smoke-tests/perf_bench_agg.py \
    --out smoke-tests/perf_logs \
    --machine laptop-cellular
python smoke-tests/perf_bench_agg.py \
    --out smoke-tests/perf_logs \
    --machine unity-cluster
```

The aggregator collapses per-run suffixes so repeats stack: log labels
`laptop-cellular`, `laptop-cellular-run2`, `laptop-cellular-run3`
collapse to one `laptop-cellular` column of min-median-max values; the
three `unity-cluster*` logs collapse to one `unity-cluster` column.
The `laptop-quick*` and `laptop-retry*` files are separate machine keys
in the aggregator output; the `docs/performance.qmd` "Laptop" column
merges them by hand into a single narrative (a cellular-tether run).

The docs pick the `laptop-cellular` and `unity-cluster` machine keys
to name the columns "Laptop" and "HPC" -- rename cosmetically as you
like when re-publishing.

## Reproducing on your own machine

The harness self-bootstraps against your local install and writes to
this directory (using its own timestamped filename, so nothing here
gets overwritten):

```bash
# One config pass, labelled by machine
python smoke-tests/perf_bench.py --configs credfree --label mylaptop

# Same via SLURM
sbatch --export=ALL,ENV_NAME=<your-env>,LABEL=mycluster \
       smoke-tests/perf_bench.slurm
```

Fresh runs land at
`smoke-tests/perf_logs/perf_bench_<label>_<ts>Z.jsonl`. Those are
gitignored by default (see `.gitignore` -- only the
`reference_2026-09-03/` snapshot is committed) so contributors don't
accidentally add every local timing they collect.

If you want your own run committed to the repo (e.g. for a follow-up
paper table), move the JSONL under a dated subfolder such as
`reference_YYYY-MM-DD/` and update `.gitignore` alongside.

## Provenance and reproducibility notes

* Fetches ran against live STAC endpoints (`earth-search.aws.element84.com`,
  `planetarycomputer.microsoft.com`) and one direct-HTTP path
  (`storage.googleapis.com` for Hansen GFC). Provider-side caches,
  network weather, and STAC index re-tiering all fluctuate over time,
  so exact wall-clock reproduction on the same machine on a later
  date is not expected -- the *shape* of the comparison
  (laptop-vs-HPC, small-vs-large AOI, setup-bound vs bandwidth-bound
  regime) is what these records support.
* The commit hash the reference runs were gathered against is
  recoverable from `git log --since=2026-08-25 --until=2026-09-10
  smoke-tests/perf_bench.py`.
* The `geoai-datacubes` version used was the pre-JOSS-review series
  (0.1.x); no fetch-path or timing-critical code changed between then
  and JOSS acceptance, so re-running against `main` today should
  produce equivalent-shape numbers modulo network variance.

## Cross-references

* Published tables and per-row narrative: [`docs/performance.qmd`](../../docs/performance.qmd).
* Aggregation code: [`smoke-tests/perf_bench_agg.py`](../perf_bench_agg.py).
* Fetch harness: [`smoke-tests/perf_bench.py`](../perf_bench.py) and
  [`smoke-tests/perf_bench.slurm`](../perf_bench.slurm).
* Raised in JOSS review at
  [openjournals/joss-reviews#11034](https://github.com/openjournals/joss-reviews/issues/11034)
  (@gmarupilla, 2026-09-16): "Could you make the raw records
  underlying the published laptop/HPC tables available, together
  with their code and environment versions, so those tables can also
  be independently reaggregated?"
