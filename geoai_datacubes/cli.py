"""``geoai-datacubes`` command line: build, style and inspect cubes by place name.

Run as ``geoai-datacubes <command>`` or ``python -m geoai_datacubes <command>``.
Every command prints how long each step took. Commands that make a map
also write a QGIS project (``.qgs``) to open.

    geoai-datacubes cube "Stromboli" --radius-km 3 --tiles
    geoai-datacubes embed-change "here" --from 2017
    geoai-datacubes embed-similar "here" --at "Ohio Stadium"
    geoai-datacubes style path/to/cube.tiff
    geoai-datacubes quality path/to/cube.tiff
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

DEFAULT_MISSIONS = "Sentinel-2,Copernicus-DEM"


class _Clock:
    """Prints per-step durations and a total at the end."""

    def __init__(self):
        self.start = self.last = time.perf_counter()
        self.steps = []

    def step(self, label):
        now = time.perf_counter()
        self.steps.append((label, now - self.last))
        self.last = now

    def report(self):
        print("\ntiming:")
        for label, s in self.steps:
            print(f"  {label:32s} {s:7.1f} s")
        print(f"  {'total':32s} {time.perf_counter() - self.start:7.1f} s")


def _slug(text):
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_") or "place"


def _newest(pattern):
    hits = glob.glob(pattern)
    return max(hits, key=os.path.getmtime) if hits else None


def _print_place(loc):
    print(f"place: {loc['name']}  ({loc['source']})")
    print(f"center: {loc['lat']:.5f}, {loc['lon']:.5f}  |  {loc['radius_km']} km radius")


def _fetch(mission, bands, time_range, bbox, folder, max_cloud, resolution=10):
    """Fetch one mission into ``folder``; return the path of its GeoTIFF."""
    from geoai_datacubes.fetch import fetch_sentinel_data

    fetch_sentinel_data(mission=mission, bands=bands, time_range=time_range, roi=bbox,
                        resolution=resolution, save_folder=str(folder),
                        max_cloud_coverage=max_cloud, provider="auto")
    path = _newest(f"{folder}/{mission}_*/{mission}_full_size.tiff")
    if path is None:
        raise RuntimeError(f"{mission} fetched but no {mission}_full_size.tiff under {folder}")
    return path


def _year_range(year):
    return (f"{year}-01-01", f"{year}-12-31")


# ---------------------------------------------------------------- commands

def cmd_geocode(a):
    from geoai_datacubes.fetch.places import locate

    loc = locate(a.place, a.radius_km)
    if a.json:
        print(json.dumps(loc, indent=1))
        return
    _print_place(loc)
    print(f"bbox: {[round(v, 6) for v in loc['bbox']]}")


def cmd_cube(a):
    from geoai_datacubes.fetch.places import locate
    from geoai_datacubes.preprocessing import fuse_response_tiffs
    from geoai_datacubes.viz.bands import display_bands
    from geoai_datacubes.viz.qgis import style_cube

    clock = _Clock()
    loc = locate(a.place, a.radius_km)
    _print_place(loc)
    out_dir = Path(a.out_dir or f"data_{_slug(a.place)}")
    out_dir.mkdir(parents=True, exist_ok=True)
    if a.year:
        time_range = _year_range(a.year)
    else:
        end = datetime.now()
        time_range = ((end - timedelta(days=30 * a.months_back)).strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
    print(f"time window: {time_range[0]} to {time_range[1]}  |  output: {out_dir}\n")
    clock.step("find place")

    inputs = []
    for mission in [m.strip() for m in a.missions.split(",") if m.strip()]:
        print(f"--- {mission} ---")
        try:
            inputs.append(_fetch(mission, display_bands(mission), time_range, loc["bbox"], out_dir,
                                 a.max_cloud, a.resolution))
            print(f"OK   {mission}")
        except Exception as e:  # keep going so one failing mission doesn't lose the others
            print(f"FAIL {mission}: {type(e).__name__}: {e}")
        clock.step(f"fetch {mission}")
    if not inputs:
        raise SystemExit("No mission fetched; nothing to fuse.")

    cube = out_dir / f"{_slug(a.place)}_cube.tiff"
    result = fuse_response_tiffs(inputs, output_path=str(cube), resolution=a.resolution)
    print(f"\ncube: {result['path']}  |  {result['shape'][0]} bands, {result['shape'][2]} x {result['shape'][1]} px")
    print(f"bands: {', '.join(result['bands'])}")
    clock.step("fuse")

    styled = style_cube(cube)
    print(f"QGIS project: {styled['project']}  ({', '.join(styled['views'])})")
    clock.step("QGIS styles")

    if a.tiles:
        _tile(cube, out_dir / "tiles", a.tile_size, a.overlap, a.split)
        clock.step("tiles")
    clock.report()


def cmd_tiles(a):
    clock = _Clock()
    cube = Path(a.cube)
    _tile(cube, Path(a.out_dir or cube.parent / "tiles"), a.tile_size, a.overlap, a.split)
    clock.step("tiles")
    clock.report()


def _tile(cube, out_dir, tile_size, overlap, split):
    from geoai_datacubes.preprocessing import tile_geotiff

    stride = max(1, round(tile_size * (1 - overlap)))
    tile_geotiff(input_tiff=str(cube), output_dir=str(out_dir), tile_size=tile_size,
                 stride=stride, split_method=split)
    counts = {s: len(list((out_dir / s).glob("*.tif"))) for s in ("train", "val", "test")}
    print(f"\ntiles: {out_dir}  |  {tile_size} px, stride {stride} ({overlap:.0%} overlap), {split} split")
    print("  " + "  ".join(f"{k} {v}" for k, v in counts.items()))
    if 0 in counts.values():
        print("  WARN a split is empty; use a larger area or smaller tiles")


def cmd_style(a):
    from geoai_datacubes.viz.qgis import style_cube

    clock = _Clock()
    styled = style_cube(a.cube)
    print(f"QGIS project: {styled['project']}  ({', '.join(styled['views'])})")
    print(f"style for the GeoTIFF alone: {styled['qml']}")
    clock.step("QGIS styles")
    clock.report()


def cmd_quality(a):
    from geoai_datacubes.viz.quality import quality_report

    print(quality_report(a.cube))


def cmd_hillshade(a):
    from geoai_datacubes.viz.terrain import write_hillshade

    out = write_hillshade(a.dem, band=a.band, out_path=a.output, z_factor=a.z_factor)
    print(f"hillshade: {out}")


def cmd_embed_change(a):
    from geoai_datacubes.fetch.places import locate
    from geoai_datacubes.viz.embeddings import change_map, latest_year, style_change

    clock = _Clock()
    loc = locate(a.place, a.radius_km)
    _print_place(loc)
    clock.step("find place")
    year_to = a.to or latest_year(loc["lon"], loc["lat"])
    out_dir = Path(a.out_dir or f"data_{_slug(a.place)}")
    paths = {}
    for year in (a.from_, year_to):
        paths[year] = _fetch("AlphaEarth", None, _year_range(year), loc["bbox"],
                             out_dir / f"alphaearth_{year}", 1.0)
        clock.step(f"fetch AlphaEarth {year}")
    out = change_map(paths[a.from_], paths[year_to], out_dir / f"alphaearth_change_{a.from_}_{year_to}.tif")
    styled = style_change(out)
    clock.step("change map + QGIS style")
    print(f"\nchange map: {out}  (0 = unchanged, higher = changed more, {a.from_} -> {year_to})")
    print(f"QGIS project: {styled['project']}")
    clock.report()


def cmd_embed_similar(a):
    from geoai_datacubes.fetch.places import locate
    from geoai_datacubes.viz.embeddings import latest_year, similarity_map, style_similarity

    clock = _Clock()
    ref = locate(a.at, 0.1)
    print(f"reference: {ref['name']}  ({ref['lat']:.5f}, {ref['lon']:.5f}, {ref['source']})")
    if Path(a.area).is_file():
        src = Path(a.area)
        out_dir = src.parent
    else:
        loc = locate(a.area, a.radius_km)
        _print_place(loc)
        clock.step("find places")
        year = a.year or latest_year(loc["lon"], loc["lat"])
        out_dir = Path(a.out_dir or f"data_{_slug(a.area)}")
        src = _fetch("AlphaEarth", None, _year_range(year), loc["bbox"], out_dir / f"alphaearth_{year}", 1.0)
        clock.step(f"fetch AlphaEarth {year}")
    out = similarity_map(src, ref["lon"], ref["lat"], out_dir / f"alphaearth_similar_to_{_slug(a.at)}.tif")
    styled = style_similarity(out)
    clock.step("similarity map + QGIS style")
    print(f"\nsimilarity map: {out}  (1 = most like the reference)")
    print(f"QGIS project: {styled['project']}")
    clock.report()


def cmd_sniff(_a):
    import importlib
    import platform

    print(f"platform: {platform.system()} {platform.release()}")
    print(f"python: {sys.version.split()[0]}")
    print(f"interpreter: {sys.executable}")
    import geoai_datacubes

    print(f"geoai_datacubes: {geoai_datacubes.__version__}")
    for pkg in ("rasterio", "pystac_client", "planetary_computer", "ee", "earthaccess",
                "geoai", "xgboost", "torch", "geopy"):
        try:
            importlib.import_module(pkg)
            print(f"  OK   {pkg}")
        except Exception:
            print(f"  MISS {pkg}")
    try:
        import google.colab  # noqa: F401
        print("env: Colab")
    except ImportError:
        print("env: local/HPC")
    cwd = Path.cwd()
    if (cwd / "agents" / "AGENTS.md").is_file() and (cwd / "geoai_datacubes").is_dir():
        print("repo: OK (geoai-datacubes)")
        pkg = Path(geoai_datacubes.__file__).resolve().parent
        if pkg == (cwd / "geoai_datacubes").resolve():
            print("package: OK (this checkout)")
        else:
            print(f"package: MISMATCH -- Python imports {pkg}, not this checkout; run from the repo root")
    else:
        print(f"repo: MISMATCH -- expected agents/AGENTS.md and geoai_datacubes/ under {cwd}")
    env = Path(sys.prefix).name
    want = os.environ.get("GEOAI_ENV_NAME", "geoai-cubes")
    print(f"conda env: {'OK' if env == want else 'MISMATCH'} ({env}{'' if env == want else f', expected {want}'})")


# ------------------------------------------------------------------ parser

def build_parser():
    p = argparse.ArgumentParser(prog="geoai-datacubes", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("geocode", help="Show where a place name resolves to")
    s.add_argument("place")
    s.add_argument("--radius-km", type=float, default=2.0)
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_geocode)

    s = sub.add_parser("cube", help="Fetch missions over a place, fuse, write QGIS styles")
    s.add_argument("place", help="Place name, alias (e.g. 'here'), or 'lat, lon'")
    s.add_argument("--missions", default=DEFAULT_MISSIONS, help=f"Comma-separated (default {DEFAULT_MISSIONS})")
    s.add_argument("--radius-km", type=float, default=2.0)
    s.add_argument("--resolution", type=float, default=10, help="Metres per pixel (default 10; NAIP is 1 m or finer)")
    s.add_argument("--months-back", type=int, default=24, help="Search window ending today (default 24)")
    s.add_argument("--year", type=int, help="Use this calendar year instead of --months-back")
    s.add_argument("--max-cloud", type=float, default=1.0,
                   help="Cloud fraction 0-1 (default 1.0: no filter, the least cloudy scene is picked)")
    s.add_argument("--out-dir")
    s.add_argument("--tiles", action="store_true", help="Also cut train/val/test tiles")
    _tile_args(s)
    s.set_defaults(func=cmd_cube)

    s = sub.add_parser("tiles", help="Cut train/val/test tiles from a cube")
    s.add_argument("cube")
    s.add_argument("--out-dir")
    _tile_args(s)
    s.set_defaults(func=cmd_tiles)

    s = sub.add_parser("style", help="Write QGIS styles (.qml) and project (.qgs) for a GeoTIFF")
    s.add_argument("cube")
    s.set_defaults(func=cmd_style)

    s = sub.add_parser("quality", help="Print a quality report for a cube")
    s.add_argument("cube")
    s.set_defaults(func=cmd_quality)

    s = sub.add_parser("hillshade", help="Write a hillshade GeoTIFF (QGIS doesn't need this)")
    s.add_argument("dem")
    s.add_argument("--band", type=int, default=1)
    s.add_argument("--z-factor", type=float, default=1.0)
    s.add_argument("-o", "--output")
    s.set_defaults(func=cmd_hillshade)

    s = sub.add_parser("embed-change", help="AlphaEarth change map between two years")
    s.add_argument("place")
    s.add_argument("--from", dest="from_", type=int, default=2017, help="First year (default 2017, the oldest)")
    s.add_argument("--to", type=int, help="Second year (default: newest published)")
    s.add_argument("--radius-km", type=float, default=2.0)
    s.add_argument("--out-dir")
    s.set_defaults(func=cmd_embed_change)

    s = sub.add_parser("embed-similar", help="AlphaEarth map of places like a reference point")
    s.add_argument("area", help="Place to search, or an existing AlphaEarth GeoTIFF")
    s.add_argument("--at", required=True, help="Reference place or 'lat, lon' (must lie inside the area)")
    s.add_argument("--year", type=int, help="AlphaEarth year (default: newest published)")
    s.add_argument("--radius-km", type=float, default=2.0)
    s.add_argument("--out-dir")
    s.set_defaults(func=cmd_embed_similar)

    s = sub.add_parser("sniff", help="Check the Python environment and repo")
    s.set_defaults(func=cmd_sniff)
    return p


def _tile_args(s):
    s.add_argument("--tile-size", type=int, default=128)
    s.add_argument("--overlap", type=float, default=0.25, help="Fraction 0-1 (default 0.25)")
    s.add_argument("--split", default="random", choices=["random", "block", "stripes"],
                   help="random keeps every split populated on small areas; block avoids neighbour leakage")


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
