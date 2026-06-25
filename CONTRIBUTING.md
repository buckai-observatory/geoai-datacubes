# Contributing to `geoai-datacubes`

Thanks for your interest in `geoai-datacubes`. This document covers
the three things JOSS asks community-driven projects to make explicit:
**how to seek support**, **how to report problems**, and **how to
contribute code, docs, or new missions**.

We are a small academic project. Expect informal, direct, low-ceremony
collaboration; we triage issues and PRs in batches rather than within
hours.

---

## 1. Seeking support / asking questions

For "how do I…" questions, use **GitHub Discussions**:

* <https://github.com/buckai-observatory/geoai-datacubes/discussions>

Discussions is the right home for: usage questions, design
questions ("which provider should I use for region X?"), feature
brainstorming, and anything that isn't a clear bug. You don't need
permissions to start a thread — open one and we'll respond.

For OSU-internal users, the BuckAI Observatory office hours and Slack
channels (`#geoai-observatory` and `#buckai-datacubes`) are the
fastest path. Non-OSU users can email
[moortgat.1@osu.edu](mailto:moortgat.1@osu.edu) for project-level
questions; please prefer Discussions for anything that might benefit
other users.

---

## 2. Reporting bugs and requesting features

Open a GitHub Issue:

* <https://github.com/buckai-observatory/geoai-datacubes/issues>

### What to include in a bug report

Please give us enough information to reproduce the problem:

* **Environment** — output of `python -V`, `pip show geoai-datacubes`,
  `pip show rasterio`, and the operating system. If you used mamba,
  the `mamba env export | head -40` output is helpful.
* **What you ran** — the smallest snippet that reproduces the bug,
  including the AOI, the mission, the date range, and the provider.
* **What happened** — the full traceback, plus the relevant log lines
  printed by the pipeline ("auto-provider: ...", "Output grid: ...",
  etc.).
* **What you expected** — one or two sentences is enough.

### What to include in a feature request

State the workflow you want to support and the part of the pipeline
that blocks it. "Add MERIT DEM" is more actionable than "More
DEMs"; "Provider auto-routing should let me override per-AOI" is
more actionable than "Better routing".

---

## 3. Contributing code

Pull requests are welcome, including from first-time contributors.

### Development setup

The recommended environment is `mamba` from `conda-forge` (the same
recipe as in [`README.md` §3](README.md#3-install-the-package)) plus
an editable install:

```bash
git clone https://github.com/buckai-observatory/geoai-datacubes.git
cd geoai-datacubes

mamba create -y -n geoai-cubes -c conda-forge \
    python=3.11 \
    rasterio gdal pyproj shapely pystac pystac-client planetary-computer \
    "pytorch>=2.0" "torchvision>=0.15" zarr lmdb scikit-image pillow \
    matplotlib numpy pandas tqdm requests
mamba activate geoai-cubes
pip install -e ".[dev]"     # core + ruff + pytest + pre-commit
```

`pip install -e ".[dev]"` brings in the lint + test tooling without
the heavy ML / DL extras. Add `[ml]`, `[geoai]`, or `[notebooks]` if
you intend to touch those parts of the codebase.

### Run the test suite

```bash
pytest                  # all tests (~2 s)
pytest tests/test_band_norm.py -v    # one file at a time
pytest -k aoi           # match by name
```

The smoke-test scripts under `smoke-tests/` are a separate kind of
test — they hit live STAC providers and take minutes to run. CI does
**not** run them; they are pre-flight checks for cluster / network
issues before a long workflow. You don't need them green to open a
PR.

### Code style and lint

We use `ruff` for both formatting and linting (config in
[`pyproject.toml`](pyproject.toml)). Before opening a PR:

```bash
ruff check geoai_datacubes tests
ruff format --check geoai_datacubes tests
```

`ruff check --fix` auto-fixes most issues. The lint step in CI is
advisory (it reports issues but doesn't fail the build), so a PR
won't be blocked on a stray style warning, but please address obvious
hits before review.

If you'd like the checks to run automatically on every commit, install
the pre-commit hooks (one-time):

```bash
pre-commit install
```

### Pull-request expectations

1. **Small, focused PRs.** One concern per PR is much easier to
   review than a mixed bag. If you're tempted to bundle a refactor
   with a bug fix, please split them.
2. **Add tests for new behaviour.** New helpers should have a unit
   test in `tests/` covering the contract. Fixing a bug? A regression
   test that fails on `main` and passes on your branch is the gold
   standard.
3. **Update the docs alongside the code.** If you change a public
   function's signature, sweep the relevant module README,
   [`docs/data_layers.md`](docs/data_layers.md) (if you touched
   mission profiles), and the top-level [README](README.md). This is
   the single thing most likely to be flagged in review.
4. **Match the existing voice.** The repo prefers technical, direct
   prose. No marketing language; no decorative emoji in public docs
   (✅ / ❌ / ⚠️ as functional indicators is fine).
5. **CI must be green.** Both Python 3.11 and 3.12 jobs in
   `.github/workflows/tests.yml` need to pass before a PR can land.
6. **Sign-off (not required, but appreciated).** Adding
   `Signed-off-by: Your Name <your@email>` at the bottom of the
   commit message helps with downstream attribution; we don't enforce
   it.

### Adding a new mission

The pipeline's mission registry is in
[`geoai_datacubes/fetch/missions.py`](geoai_datacubes/fetch/missions.py),
with detailed instructions in
[`docs/adding_a_mission.md`](docs/adding_a_mission.md). A complete
mission addition typically touches:

* `geoai_datacubes/fetch/missions.py` — add a `MISSION_PROFILES`
  entry with `default_bands` / `extra_bands` / `band_meta` /
  `providers`.
* `geoai_datacubes/fetch/fetch_data.py` — add the mission to
  `PROVIDER_AUTO` so the default `provider="auto"` routes to it.
* `docs/data_layers.md` — band table, value range, normalisation recipe.
* `smoke-tests/fetch_<mission>.sh` — a SLURM-or-bash test that fetches
  a tiny AOI to verify the integration.
* `tests/test_missions.py` — add the new mission name to
  `_EXPECTED_MISSIONS` so the structural test catches regressions.

For missions that are *not* in any STAC catalogue (e.g. raw COGs on
Google Cloud Storage), use the `direct_http` provider class
documented in [`docs/providers.md`](docs/providers.md); Hansen-GFC is
the reference implementation.

---

## 4. Contributing documentation

The repo is documentation-heavy — that's intentional. Documentation
PRs (typo fixes, clarifications, missing sections, screenshots) are
just as welcome as code PRs.

If your change touches public surface (a new function, a renamed
argument, a removed parameter, a new mission, a new preset), please
sweep **all** the affected `.md` files in one PR rather than batching
the doc update for later:

* `README.md` (top-level)
* `notebooks/README.md`
* the module-level README under the directory you modified
  (`geoai_datacubes/<subpkg>/README.md`)
* `paper.md` if your change affects the JOSS-paper narrative
* `CHANGELOG.md` for visible behaviour changes

`docs/HPC_RUNBOOK.md` is intentionally local-only and is excluded
from git (see `.gitignore`); please don't push your local copy.

---

## 5. Notebook contributions

The four notebooks under `notebooks/` are pedagogical material that
ships in the repo. When you edit one:

* Strip embedded outputs from very-large notebooks before committing
  (`jupyter nbconvert --clear-output --inplace <notebook>` or
  `nbstripout`). Outputs are byte-heavy and inflate the repo.
  *Exception:* if a notebook's small figures are essential to its
  pedagogy, keeping them is fine — review will flag if a notebook
  grows by tens of MB.
* Run the notebook end-to-end on a fresh kernel before pushing.
* If you add a new notebook, update both `README.md` and
  `notebooks/README.md` so it appears in the "Try the notebooks"
  section with a Colab badge.

---

## 6. Code of conduct

We follow the **Contributor Covenant v2.1**; see [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md)
for the full text and the reporting / enforcement workflow. In one sentence:
be respectful, assume good faith, and remember that this is an academic
project run by humans with limited bandwidth.

Violations or concerns: [moortgat.1@osu.edu](mailto:moortgat.1@osu.edu).
Reports are handled confidentially.

---

## 7. Licensing

By contributing, you agree that your contributions are licensed under
the same [MIT License](LICENSE) that covers the rest of the project.
Significant contributors are added to
[`CONTRIBUTORS.md`](CONTRIBUTORS.md); we are happy to credit
single-PR contributors there as well.

---

## 8. Project context

`geoai-datacubes` is developed at the
[**BuckAI Observatory**](https://buckai-observatory.org) at
The Ohio State University, with primary maintainership from
[Joachim Moortgat](https://earthsciences.osu.edu/people/moortgat.1)
(School of Earth Sciences). The project's broader scientific
positioning — what it does, what it does not do, how it relates to
other open-source EO and geoAI tools — is in
[`paper.md`](paper.md). The
[GeoAI Book](https://book.opengeoai.org/) (Wu, 2026) is a useful
companion for the downstream-modelling half of the workflow.

Thanks again — looking forward to your contributions.
