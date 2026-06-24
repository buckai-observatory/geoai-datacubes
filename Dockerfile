# geoai-datacubes -- full image with JupyterLab + the four pedagogical notebooks.
#
# Builds on `mambaorg/micromamba` and installs the full `geoai-cubes` stack
# (the same set of conda-forge packages the README recommends) plus
# JupyterLab and the geoai-datacubes wheel from PyPI. The four notebooks
# ship inside the image at /home/mambauser/notebooks/ so users can be
# poking at real data within seconds of `docker run`.
#
# Usage:
#
#     docker run -p 127.0.0.1:8888:8888 \
#         ghcr.io/buckai-observatory/geoai-datacubes:latest
#
# The container prints a JupyterLab URL with a one-time token; copy it
# into your browser. To set a fixed password instead:
#
#     docker run -e JUPYTER_TOKEN=mytoken -p 127.0.0.1:8888:8888 \
#         ghcr.io/buckai-observatory/geoai-datacubes:latest
#
# To mount a local folder for persistent outputs:
#
#     docker run -p 127.0.0.1:8888:8888 -v "$PWD/outputs:/home/mambauser/work" \
#         ghcr.io/buckai-observatory/geoai-datacubes:latest

ARG MAMBA_BASE=mambaorg/micromamba:2.0-noble
FROM ${MAMBA_BASE}

ARG GEOAI_DATACUBES_VERSION=""

# OCI labels surface in GHCR's UI and on `docker inspect`.
LABEL org.opencontainers.image.source="https://github.com/buckai-observatory/geoai-datacubes"
LABEL org.opencontainers.image.description="AI-ready multi-mission Earth-observation data cubes (pipeline + four pedagogical notebooks + JupyterLab)"
LABEL org.opencontainers.image.licenses="MIT"
LABEL org.opencontainers.image.title="geoai-datacubes"
LABEL org.opencontainers.image.authors="Joachim Moortgat <moortgat.1@osu.edu>"
LABEL org.opencontainers.image.documentation="https://github.com/buckai-observatory/geoai-datacubes#readme"

# tini gives us proper SIGTERM forwarding to JupyterLab; git is useful
# for users who want to clone follow-on repos alongside the notebooks.
USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
        git tini ca-certificates && \
    rm -rf /var/lib/apt/lists/*

USER $MAMBA_USER
ARG MAMBA_DOCKERFILE_ACTIVATE=1
WORKDIR /home/$MAMBA_USER

# Install the full geoai-cubes conda-forge stack in one layer. This
# mirrors the recommended `mamba create -n geoai-cubes ...` command in
# README.md section 3, with the addition of `segmentation-models-pytorch`
# and `pytest` for the integration notebook + test suite.
RUN micromamba install -n base -y -c conda-forge \
        python=3.11 \
        geoai-py leafmap torchgeo omniwatermask \
        rasterio gdal pyproj shapely \
        pystac pystac-client planetary-computer \
        "pytorch>=2.0" "torchvision>=0.15" \
        zarr lmdb scikit-image pillow \
        matplotlib numpy pandas tqdm requests \
        scikit-learn xgboost ultralytics transformers \
        jupyterlab ipywidgets seaborn geopandas contextily \
        segmentation-models-pytorch pytest && \
    micromamba clean --all --yes

# Install geoai-datacubes itself from PyPI. Pinned to a specific version
# at build time via build-arg; falls back to "latest" if not provided.
# Empty string -> install latest; explicit version -> install that.
RUN if [ -n "${GEOAI_DATACUBES_VERSION}" ]; then \
        pip install --no-cache-dir "geoai-datacubes==${GEOAI_DATACUBES_VERSION}"; \
    else \
        pip install --no-cache-dir geoai-datacubes; \
    fi

# Bring the four pedagogical notebooks + small sample data into the image
# at the user's home so they appear in the JupyterLab file browser.
COPY --chown=$MAMBA_USER:$MAMBA_USER notebooks /home/$MAMBA_USER/notebooks
COPY --chown=$MAMBA_USER:$MAMBA_USER README.md /home/$MAMBA_USER/README.md
COPY --chown=$MAMBA_USER:$MAMBA_USER LICENSE   /home/$MAMBA_USER/LICENSE

# Persistent-output mount-point hint.
RUN mkdir -p /home/$MAMBA_USER/work

EXPOSE 8888

# tini as PID 1 -> clean shutdown on `docker stop`. JupyterLab generates
# a one-time token by default; override with `-e JUPYTER_TOKEN=...`.
ENTRYPOINT ["tini", "--"]
CMD ["jupyter", "lab", \
     "--ip=0.0.0.0", \
     "--port=8888", \
     "--no-browser", \
     "--ServerApp.root_dir=/home/mambauser"]
