"""Quality report for a fused cube: band statistics, missing data, class
histograms, NDVI and a rough score.

Each band is reported under the section its kind implies (optical, SAR,
class labels, elevation, ...), looked up in ``MISSION_PROFILES`` through
:mod:`geoai_datacubes.viz.bands`, so it works for any mission mix. NDVI
uses each mission's own red/near-infrared band codes.

This is the mechanical half of a report. What the numbers mean for a
given use ("fine for vegetation mapping, too cloudy for water") is left
to the reader.
"""
from pathlib import Path

import numpy as np
import rasterio

from geoai_datacubes.fetch.missions import MISSION_PROFILES

from .bands import legend_for, resolve_band

CLOUD_CLASSES = {8, 9, 10}


def pct(n, total):
    return 100 * n / total if total else 0.0


def _numeric_stats(out, bands, arr_by_band):
    for i, name in bands:
        v = arr_by_band[i][~np.isnan(arr_by_band[i])]
        if v.size:
            out(f"   {name:28s} min={v.min():.2f}  max={v.max():.2f}  mean={v.mean():.2f} +/- {v.std():.2f}")


def quality_report(path) -> str:
    """Quality report for a fused cube, as printable text."""
    path = Path(path)
    lines = []
    out = lines.append

    with rasterio.open(path) as src:
        count = src.count
        names = list(src.descriptions or [f"band_{i}" for i in range(1, count + 1)])
        h, w = src.height, src.width
        res = src.res
        crs = src.crs
        arr = {i: src.read(i).astype(float) for i in range(1, count + 1)}

    total_px = h * w
    score_components = []  # (label, earned_0_25)

    # Resolve every band once, and bucket by kind.
    resolved = {i: resolve_band(name) for i, name in enumerate(names, start=1)}
    buckets = {}
    for i, (mission, bandcode, kind, meta) in resolved.items():
        buckets.setdefault(kind, []).append((i, names[i - 1]))

    out("=" * 70)
    out(f"QUALITY REPORT -- {path.name}")
    out("=" * 70)

    # 1. Spatial metadata
    out("\n1. SPATIAL METADATA")
    out("-" * 70)
    out(f"   Dimensions:        {w} x {h} px, {count} bands")
    out(f"   Resolution:        {res[0]:.2f} m/px -> {w*res[0]/1000:.2f} x {h*res[1]/1000:.2f} km")
    out(f"   CRS:               {crs}")
    out(f"   Bands:             {', '.join(names)}")
    unresolved = [n for i, n in enumerate(names, start=1) if resolved[i][0] is None]
    if unresolved:
        out(f"   Not in mission registry (generic stats only): {', '.join(unresolved)}")

    # 2. Data completeness
    out("\n2. DATA COMPLETENESS")
    out("-" * 70)
    nan_fracs = []
    for i, name in enumerate(names, start=1):
        n_nan = int(np.isnan(arr[i]).sum())
        p = pct(n_nan, total_px)
        nan_fracs.append(p)
        out(f"   {name:28s} {n_nan:>9,} NaN px ({p:.3f}%)")
    avg_nan = sum(nan_fracs) / len(nan_fracs) if nan_fracs else 0
    completeness_score = 25 * max(0, 1 - avg_nan / 5)  # <0.1% avg -> ~full credit, 5%+ -> 0
    score_components.append(("Data completeness", completeness_score))

    # 3. Scene classification (SCL specifically -- rich legend + cloud/snow/water/veg summary)
    for i, name in buckets.get("scl", []):
        out(f"\n3. SCENE CLASSIFICATION ({name})")
        out("-" * 70)
        scl_legend = legend_for(resolved[i][0], resolved[i][1], "scl")
        valid = arr[i][~np.isnan(arr[i])].astype(int)
        unique, counts = np.unique(valid, return_counts=True)
        for cls, cnt in zip(unique, counts):
            label = scl_legend.get(cls, ("UNKNOWN", None))[0]
            out(f"   {cls:2d} {label:26s} {cnt:>9,} px ({pct(cnt, total_px):5.2f}%)")
        cloud_px = sum(c for cls, c in zip(unique, counts) if cls in CLOUD_CLASSES)
        snow_px = sum(c for cls, c in zip(unique, counts) if cls == 11)
        water_px = sum(c for cls, c in zip(unique, counts) if cls == 6)
        veg_px = sum(c for cls, c in zip(unique, counts) if cls == 4)
        cloud_pct = pct(cloud_px, total_px)
        out(f"\n   Cloud cover: {cloud_pct:.2f}%  |  Snow: {pct(snow_px, total_px):.2f}%  "
              f"|  Water: {pct(water_px, total_px):.2f}%  |  Vegetation: {pct(veg_px, total_px):.2f}%")
        score_components.append(("Cloud cover", 25 if cloud_pct < 1 else 20 if cloud_pct < 5 else 10))

    # 4. Any other categorical band (LULC from any provider, JRC-GSW transitions/extent, etc.)
    if buckets.get("categorical"):
        out("\n4. CATEGORICAL / LABEL BANDS")
        out("-" * 70)
        for i, name in buckets["categorical"]:
            mission, bandcode = resolved[i][0], resolved[i][1]
            legend = legend_for(mission, bandcode, "categorical") or {}
            valid = arr[i][~np.isnan(arr[i])].astype(int)
            unique, counts = np.unique(valid, return_counts=True)
            out(f"   {name}:")
            for cls, cnt in zip(unique, counts):
                label = legend.get(cls, (f"class {cls}", None))[0]
                out(f"      {cls:>4d} {label:24s} {cnt:>9,} px ({pct(cnt, total_px):5.2f}%)")

    # 5. Optical spectral bands + per-mission NDVI
    if buckets.get("spectral"):
        out("\n5. SPECTRAL / OPTICAL BANDS")
        out("-" * 70)
        _numeric_stats(out, buckets["spectral"], arr)

        # Group spectral bands by mission so NDVI uses each mission's own
        # registered red/nir codes (Sentinel-2: B04/B08, Landsat: B04/B05, ...).
        by_mission = {}
        for i, name in buckets["spectral"]:
            mission = resolved[i][0]
            by_mission.setdefault(mission, {})[resolved[i][1]] = i
        for mission, code_to_i in by_mission.items():
            ndvi_spec = (MISSION_PROFILES.get(mission, {}) or {}).get("ndvi")
            if not ndvi_spec:
                continue
            red_i = code_to_i.get(ndvi_spec["red"])
            nir_i = code_to_i.get(ndvi_spec["nir"])
            if red_i is None or nir_i is None:
                continue
            mask = ~(np.isnan(arr[red_i]) | np.isnan(arr[nir_i]))
            red, nir = arr[red_i][mask], arr[nir_i][mask]
            ndvi = (nir - red) / (nir + red + 1e-8)
            out(f"\n   NDVI [{mission}] ({ndvi_spec['nir']}-{ndvi_spec['red']})/({ndvi_spec['nir']}+{ndvi_spec['red']}): "
                  f"mean={ndvi.mean():.3f}  range=[{ndvi.min():.3f}, {ndvi.max():.3f}]  "
                  f"healthy(>0.6)={pct((ndvi > 0.6).sum(), ndvi.size):.1f}%")

    # 6. SAR backscatter
    if buckets.get("sar"):
        out("\n6. SAR BACKSCATTER")
        out("-" * 70)
        _numeric_stats(out, buckets["sar"], arr)
        out("   (values are log-scaled backscatter (dB) per the mission's norm spec,")
        out("    not directly comparable to optical reflectance ranges above)")

    # 7. QA / auxiliary bands (AOT, WVP, cloud-prob flags, etc. -- excludes SCL, handled above)
    qa_bands = buckets.get("qa", []) + buckets.get("qa_bits", [])
    if qa_bands:
        out("\n7. QA / AUXILIARY BANDS")
        out("-" * 70)
        _numeric_stats(out, qa_bands, arr)
        aot = next((i for i, n in qa_bands if resolved[i][1] == "AOT"), None)
        if aot:
            v = arr[aot][~np.isnan(arr[aot])]
            score_components.append(("Atmospheric clarity", 25 if v.mean() < 20 else 20 if v.mean() < 50 else 10))

    # 8. Topography (elevation + altimetry -- DEM, ArcticDEM, GEBCO, ICESat-2, ...)
    topo_bands = buckets.get("elevation", []) + buckets.get("altimetry", [])
    if topo_bands:
        out("\n8. TOPOGRAPHY / ELEVATION")
        out("-" * 70)
        for i, name in topo_bands:
            v = arr[i][~np.isnan(arr[i])]
            if not v.size:
                continue
            out(f"   {name}: {v.min():.0f} to {v.max():.0f}  (mean {v.mean():.0f})  "
                  f"relief={v.max()-v.min():.0f}  roughness(std)={v.std():.0f}")
            score_components.append(("Terrain diversity", 25 if v.std() > 200 else 20 if v.std() > 50 else 15))

    # 9. Everything else numeric (continuous, fraction, index, temperature, unknown)
    other_kinds = {"continuous", "fraction", "index", "temperature", "unknown"}
    other_bands = [b for k in other_kinds for b in buckets.get(k, [])]
    if other_bands:
        out("\n9. OTHER BANDS")
        out("-" * 70)
        _numeric_stats(out, other_bands, arr)

    # 10. Overall score, reweighted over whichever components exist
    out("\n10. OVERALL SCORE")
    out("-" * 70)
    for label, earned in score_components:
        out(f"   {label:24s} {earned:.0f}/25")
    total = 100 * sum(e for _, e in score_components) / (25 * len(score_components)) if score_components else 0
    total = round(total)
    grade = "A" if total >= 85 else "B" if total >= 75 else "C" if total >= 60 else "D"
    if score_components:
        out(f"\n   SCORE: {total}/100  (grade {grade})")
    else:
        out("\n   No scoreable categories found (no SCL/AOT/elevation band) -- "
              "completeness above is the only universal signal.")
    out("=" * 70)
    return "\n".join(lines)
