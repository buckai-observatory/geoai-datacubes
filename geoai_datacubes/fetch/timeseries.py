"""Multi-temporal fetch: same AOI, same grid, many dates.

For the common case of building a time-stack over one AOI ("give me
Sentinel-2 over Lake Erie every month for a year"), this module wraps
the per-date fetch loop and guarantees every date lands on
byte-identical rasters -- the invariant AI-ready cubes need.

Two output modes:

* ``output="list"`` (default) -- one GeoTIFF per date under
  ``<save_folder>/<mission>_<YYYYMMDD>_series/`` folders, returned as a
  list of dicts. Downstream code slices them like any other cube;
  ``LazyTileDataset`` handles a list of files natively.
* ``output="stacked"`` -- one Zarr array with shape ``(T, H, W, C)``
  under ``<save_folder>/<mission>_<start>_<end>_stacked.zarr``. The
  natural container for RNN / transformer / video-model workflows,
  phenology curves, and change detection. ``time_coords`` metadata
  is written to the Zarr attrs so downstream code can align timesteps
  to dates.

The grid is picked once via :func:`~.plan_grid.plan_grid` (or supplied
by the caller as ``grid=``) and passed to every per-date fetch, so:

* Two identical calls produce byte-identical outputs.
* Two calls with different time_ranges but the same AOI + resolution
  still produce grid-aligned outputs.
* Missions align cross-provider (S2 via earthsearch + S1 via
  planetary_computer + DEM via direct_http, all on the same grid).

Related: https://github.com/buckai-observatory/geoai-datacubes/issues/35
"""
from __future__ import annotations

import datetime as _dt
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np
import rasterio

from .fetch_data import fetch_sentinel_data
from .plan_grid import Grid, plan_grid


__all__ = ["fetch_time_series", "TimeSeriesEntry"]


@dataclass(frozen=True)
class TimeSeriesEntry:
    """One timestep of a multi-temporal fetch.

    Attributes
    ----------
    time_range : (str, str)
        The requested ``(start_iso, end_iso)`` window.
    path : str
        Absolute path to the written ``<mission>_full_size.tiff`` for
        this timestep. For ``output="stacked"``, this is the Zarr path
        (same for every entry) and ``time_index`` names the slice.
    time_index : int
        0-based index in the series.
    data : list[numpy.ndarray] or None
        Per-band arrays, as returned by the underlying fetch call.
        Set to ``None`` when materialising a large stack is expensive
        and the caller only needs the file paths.
    bands : list[str]
        Ordered list of band names actually returned.
    ok : bool
        True if the fetch succeeded. Failed timesteps still get an
        entry (so the caller sees the gap) with ``ok=False`` and
        ``error`` set.
    error : str or None
        Exception ``"<Type>: <message>"`` string when ``ok=False``.
    """
    time_range: Tuple[str, str]
    path: str
    time_index: int
    data: Optional[List[np.ndarray]]
    bands: List[str]
    ok: bool
    error: Optional[str] = None


def fetch_time_series(
    mission: str,
    bands: Optional[Sequence[str]],
    aoi: Sequence[float],
    time_ranges: Sequence[Tuple[str, str]],
    *,
    resolution: float = 10,
    save_folder: str = "data",
    provider: str = "auto",
    grid: Optional[Grid] = None,
    output: str = "list",
    on_error: str = "record",
    max_cloud_coverage: float = 0.10,
    min_cloud_coverage: float = 0.0,
    stacked_name: Optional[str] = None,
    return_arrays: bool = True,
) -> Union[List[TimeSeriesEntry], Dict[str, Any]]:
    """Fetch the same AOI + bands at multiple date windows onto ONE grid.

    Parameters
    ----------
    mission, bands, aoi, resolution, save_folder, provider,
    max_cloud_coverage, min_cloud_coverage :
        Forwarded to :func:`~.fetch_data.fetch_sentinel_data` per
        timestep. See its docstring.
    time_ranges : sequence of (start_iso, end_iso)
        The date windows. Each becomes one timestep. Windows that
        return no scenes surface as ``ok=False`` entries in the
        result rather than raising, so a season with cloudy weeks
        still yields a well-formed time series with gaps documented.
    grid : Grid, optional
        Pin every fetch onto this grid. When ``None``, the fetcher
        auto-plans a deterministic AOI-centroid grid once via
        :func:`~.plan_grid.plan_grid` and passes it to every call.
    output : "list" or "stacked"
        * ``"list"`` (default) -- returns a list of
          :class:`TimeSeriesEntry`, one per date. Each has its own
          on-disk GeoTIFF under
          ``<save_folder>/<mission>_<YYYYMMDD>_series/``.
        * ``"stacked"`` -- writes one Zarr under
          ``<save_folder>/<mission>_<first>_<last>_stacked.zarr`` with
          shape ``(T, H, W, C)`` (chunks ``(1, H, W, C)``), and
          returns a dict:
          ``{"path": str, "shape": (T,H,W,C), "bands": [...],
             "time_ranges": [...], "grid": Grid, "entries": [...]}``.
    on_error : "record" or "raise"
        ``"record"`` (default) -- per-timestep exceptions become
        ``ok=False`` entries and the loop continues. ``"raise"`` --
        the first exception aborts.
    stacked_name : str, optional
        Override the stacked Zarr basename (without ``.zarr``). By
        default the name encodes the first and last time_range's
        start date.
    return_arrays : bool
        ``True`` (default) -- populate ``entry.data`` with the
        per-band arrays. ``False`` -- entries carry file paths only
        (cheaper for large series where the caller reads on demand).

    Returns
    -------
    list of TimeSeriesEntry, or dict when ``output="stacked"``.

    Notes
    -----
    * The grid is planned once and reused across every timestep. If
      the caller wants a shared grid across multiple missions too,
      build one grid, pass ``grid=`` here, and pass the same grid to
      every ``fetch_sentinel_data`` call outside this loop.
    * ``output="stacked"`` requires every timestep to fetch every band
      in the same order; a mismatch (e.g. an S2 scene missing a band
      that other dates have) aborts the stacked-write with a clear
      error.
    * ``output="stacked"`` currently writes a single-precision
      float32 Zarr with ``nan`` as nodata, mirroring the on-disk
      GeoTIFFs. int / uint output plus per-band scale/offset is
      future work.
    """
    if output not in ("list", "stacked"):
        raise ValueError(f"output must be 'list' or 'stacked'; got {output!r}")
    if on_error not in ("record", "raise"):
        raise ValueError(f"on_error must be 'record' or 'raise'; got {on_error!r}")
    if not time_ranges:
        raise ValueError("fetch_time_series: time_ranges must be non-empty")

    # Plan the grid once so every date lands on identical rasters.
    if grid is None:
        grid = plan_grid(aoi, resolution)
    print(
        f"fetch_time_series: {mission} · {len(time_ranges)} date window(s) "
        f"· grid {grid.shape[1]}x{grid.shape[0]} px @ {resolution} m in "
        f"{grid.crs}"
    )

    save_root = Path(save_folder)
    save_root.mkdir(parents=True, exist_ok=True)

    entries: List[TimeSeriesEntry] = []
    per_date_arrays: List[List[np.ndarray]] = []
    stacked_bands: Optional[List[str]] = None

    for i, tr in enumerate(time_ranges):
        start_tag = tr[0].replace("-", "")[:8] or f"t{i:02d}"
        per_date_folder = str(save_root / f"{mission}_{start_tag}_series")
        try:
            data, final_bands = fetch_sentinel_data(
                mission, bands, tr, aoi,
                resolution=resolution,
                save_folder=per_date_folder,
                max_cloud_coverage=max_cloud_coverage,
                min_cloud_coverage=min_cloud_coverage,
                provider=provider,
                grid=grid,
            )
        except Exception as exc:
            err = f"{type(exc).__name__}: {exc}"
            print(f"  [{i+1}/{len(time_ranges)}] {tr[0]}..{tr[1]}  ✗ {err}")
            if on_error == "raise":
                raise
            entries.append(TimeSeriesEntry(
                time_range=tuple(tr), path="", time_index=i,
                data=None, bands=[], ok=False, error=err,
            ))
            if output == "stacked":
                per_date_arrays.append(None)  # type: ignore[arg-type]
            continue

        # Recover the on-disk path (the fetch just wrote it).
        tif = _find_written_tiff(per_date_folder, mission)
        entries.append(TimeSeriesEntry(
            time_range=tuple(tr), path=tif, time_index=i,
            data=(list(data) if return_arrays else None),
            bands=list(final_bands), ok=True, error=None,
        ))
        if output == "stacked":
            per_date_arrays.append(list(data))
            if stacked_bands is None:
                stacked_bands = list(final_bands)
            elif list(final_bands) != stacked_bands:
                raise RuntimeError(
                    f"fetch_time_series output='stacked': timestep {i} "
                    f"returned bands {list(final_bands)}, but the first "
                    f"successful timestep returned {stacked_bands}. Every "
                    f"timestep must return the same bands in the same "
                    f"order to stack. Use output='list' when bands vary "
                    f"per date."
                )
        print(f"  [{i+1}/{len(time_ranges)}] {tr[0]}..{tr[1]}  ✓ -> {tif}")

    if output == "list":
        return entries

    # ---- output == "stacked" ------------------------------------------
    if stacked_bands is None:
        raise RuntimeError(
            "fetch_time_series output='stacked': every timestep failed; "
            "no data to stack. Inspect the returned entries for errors."
        )

    T = len(time_ranges)
    H, W = grid.shape
    C = len(stacked_bands)

    tag = stacked_name or (
        f"{time_ranges[0][0].replace('-','')[:8]}_"
        f"{time_ranges[-1][1].replace('-','')[:8]}"
    )
    zarr_path = save_root / f"{mission}_{tag}_stacked.zarr"

    # zarr>=2.16,<3 API. Use fill_value=nan and float32 to mirror the
    # per-date GeoTIFFs and let downstream code detect gaps.
    import zarr  # noqa: PLC0415 -- keep the top-level import light
    z = zarr.open_array(
        str(zarr_path),
        mode="w",
        shape=(T, H, W, C),
        chunks=(1, H, W, C),
        dtype="float32",
        fill_value=float("nan"),
    )
    for i, arrs in enumerate(per_date_arrays):
        if arrs is None:
            continue  # leave the whole timestep as NaN
        for k, a in enumerate(arrs):
            z[i, :, :, k] = a.astype("float32", copy=False)

    # Rich metadata for downstream code.
    z.attrs["mission"] = mission
    z.attrs["bands"] = stacked_bands
    z.attrs["time_ranges"] = [list(tr) for tr in time_ranges]
    z.attrs["time_starts"] = [tr[0] for tr in time_ranges]
    z.attrs["time_ends"] = [tr[1] for tr in time_ranges]
    z.attrs["ok_mask"] = [bool(e.ok) for e in entries]
    z.attrs["errors"] = [e.error or "" for e in entries]
    z.attrs["grid"] = grid.as_dict()
    z.attrs["resolution_m"] = float(resolution)
    z.attrs["aoi_wgs84"] = list(map(float, aoi))
    z.attrs["provider"] = provider
    z.attrs["written_at"] = _dt.datetime.utcnow().isoformat(timespec="seconds") + "Z"

    print(f"fetch_time_series: wrote {zarr_path}  shape=({T},{H},{W},{C})")

    return {
        "path": str(zarr_path),
        "shape": (T, H, W, C),
        "bands": stacked_bands,
        "time_ranges": [list(tr) for tr in time_ranges],
        "grid": grid,
        "entries": entries,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_written_tiff(save_folder: str, mission: str) -> str:
    """Return the newest ``<mission>_full_size.tiff`` under a save folder.

    Every provider writes to
    ``<save_folder>/<scene_id>/<mission>_full_size.tiff`` (or
    ``<mission>_full_size.tif``). We take the most-recently-mtime'd
    match so the same folder can be reused across repeat fetches
    without stale-file confusion.
    """
    root = Path(save_folder)
    candidates: List[Tuple[float, str]] = []
    for pat in (
        f"**/{mission}_full_size.tiff",
        f"**/{mission}_full_size.tif",
    ):
        for p in root.glob(pat):
            try:
                candidates.append((p.stat().st_mtime, str(p)))
            except OSError:
                continue
    if not candidates:
        raise FileNotFoundError(
            f"fetch_time_series: expected "
            f"<save_folder>/*/{mission}_full_size.tiff under {root} but "
            f"none was found. Did the provider write elsewhere?"
        )
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]
