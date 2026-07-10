#!/bin/sh
# Post-render cleanup for the Quarto docs site.
#
# Quarto copies every non-hidden project file into _site/ by default,
# treating them as "resources". This script deletes the Python
# package, notebooks, tests, packaging metadata, and other non-doc
# files from the rendered output so they don't ship on the docs site.
#
# Intentionally does NOT use `set -e`: every rm here is a best-effort
# cleanup, and a missing file is not a failure. All rm commands use
# `-f` so they don't error on missing paths.

TARGET_DIR="${QUARTO_PROJECT_OUTPUT_DIR:-_site}"

if [ ! -d "$TARGET_DIR" ]; then
    echo "quarto-cleanup: $TARGET_DIR not found; nothing to clean." >&2
    exit 0
fi

cd "$TARGET_DIR"

# Directories (Python package + tests + notebooks + slurm scaffolding)
rm -rf geoai_datacubes notebooks smoke-tests slurm_examples modules tests __pycache__

# Root files (packaging, LICENSE, JOSS paper sources, README)
rm -f Dockerfile LICENSE README.md paper.md paper.bib \
      pyproject.toml MANIFEST.in CITATION.cff .mailmap .env.example

# Local-only HPC runbook that must never leak
rm -f docs/HPC_RUNBOOK.md

# Any raw .md files that Quarto rendered to .html (defensive: keep the
# rendered site .html-only under docs/).
rm -f docs/install.md docs/credentials.md docs/providers.md \
      docs/data_layers.md docs/adding_a_mission.md \
      docs/configuration.md docs/fusion.md \
      docs/HPC_QUICKSTART.md docs/project_structure.md

exit 0
