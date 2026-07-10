#!/bin/sh
# Post-render cleanup for the Quarto docs site.
#
# Quarto copies every non-hidden project file into _site/ by default,
# treating them as "resources". This script deletes the Python
# package, notebooks, tests, packaging metadata, and other non-doc
# files from the rendered output so they don't ship on the docs site.
set -eu

TARGET_DIR="${QUARTO_PROJECT_OUTPUT_DIR:-_site}"

cd "$TARGET_DIR"

# Directories (Python package + tests + notebooks + slurm scaffolding)
rm -rf \
    geoai_datacubes \
    notebooks \
    smoke-tests \
    slurm_examples \
    modules \
    tests \
    __pycache__

# Root files (packaging, LICENCE, JOSS paper sources, README)
rm -f \
    Dockerfile \
    LICENSE \
    README.md \
    paper.md \
    paper.bib \
    pyproject.toml \
    MANIFEST.in \
    CITATION.cff \
    .mailmap \
    .env.example

# Local-only HPC runbook that must never leak
rm -f docs/HPC_RUNBOOK.md

# `docs/` may also have the raw .md files alongside the rendered .html
# from earlier Quarto builds. Remove any lingering .md that was
# rendered to .html (guaranteed clean rebuild).
for md in docs/install.md docs/credentials.md docs/providers.md \
          docs/data_layers.md docs/adding_a_mission.md \
          docs/configuration.md docs/fusion.md \
          docs/HPC_QUICKSTART.md docs/project_structure.md ; do
    [ -f "$md" ] && rm -f "$md"
done
