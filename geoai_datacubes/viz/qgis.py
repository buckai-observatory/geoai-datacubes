"""QGIS styles for cubes, written as plain XML (no QGIS install needed).

Two outputs per cube:

* ``<stem>.qml`` next to the GeoTIFF. QGIS applies a same-named ``.qml``
  automatically, so opening the GeoTIFF on its own shows its main view.
* ``<stem>.qgs``, a QGIS project that opens the same file several times,
  once per view: natural colour for optical bands, hillshade for
  elevation, a labelled legend for class bands. This is how a mixed cube
  gets several styles without writing extra GeoTIFFs.

Which views a cube gets is decided per band from ``MISSION_PROFILES``
(see :mod:`geoai_datacubes.viz.bands`). A cube without natural-colour
bands does not get a fake RGB view; 64 AlphaEarth bands, for example,
get none.

The XML follows what QGIS 3.44 itself writes; files are checked by
loading them with PyQGIS in the test suite when PyQGIS is available.
"""
from __future__ import annotations

import uuid
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

import numpy as np
import rasterio

from .bands import FALLBACK_COLORS, TRUE_COLOR, legend_for, resolve_bands

# Perceptually uniform, colour-blind-safe ramp (viridis); lightness rises
# monotonically, so it also reads correctly in greyscale.
VIRIDIS = ["#440154", "#3b528b", "#21918c", "#5ec962", "#fde725"]

_MINMAX = """<minMaxOrigin><limits>None</limits><extent>WholeRaster</extent><statAccuracy>Estimated</statAccuracy><cumulativeCutLower>0.02</cumulativeCutLower><cumulativeCutUpper>0.98</cumulativeCutUpper><stdDevFactor>2</stdDevFactor></minMaxOrigin>"""

_PIPE = """<pipe>
      <provider><resampling maxOversampling="2" zoomedOutResamplingMethod="{resample}" enabled="false" zoomedInResamplingMethod="{resample}"/></provider>
      {renderer}
      <brightnesscontrast contrast="0" gamma="1" brightness="0"/>
      <huesaturation grayscaleMode="0" colorizeBlue="128" colorizeOn="0" colorizeGreen="128" colorizeStrength="100" colorizeRed="255" invertColors="0" saturation="0"/>
      <rasterresampler maxOversampling="2"/>
      <resamplingStage>resamplingFilter</resamplingStage>
    </pipe>"""


# ---------------------------------------------------------------- renderers

def rgb_renderer(bands, lows, highs) -> str:
    """Natural-colour renderer. ``bands`` are 1-indexed (r, g, b)."""
    parts = []
    for color, lo, hi in zip(("red", "green", "blue"), lows, highs):
        parts.append(f"<{color}ContrastEnhancement><minValue>{lo:.6g}</minValue><maxValue>{hi:.6g}</maxValue>"
                     f"<algorithm>StretchToMinimumMaximum</algorithm></{color}ContrastEnhancement>")
    r, g, b = bands
    return (f'<rasterrenderer type="multibandcolor" redBand="{r}" greenBand="{g}" blueBand="{b}" '
            f'opacity="1" alphaBand="-1" nodataColor="">{_MINMAX}{"".join(parts)}</rasterrenderer>')


def hillshade_renderer(band: int, z_factor: float = 1.0, azimuth: float = 315, altitude: float = 45) -> str:
    """QGIS's own hillshade renderer, computed live from an elevation band."""
    return (f'<rasterrenderer type="hillshade" band="{band}" opacity="1" alphaBand="-1" angle="{altitude:g}" '
            f'azimuth="{azimuth:g}" nodataColor="" multidirection="0" zfactor="{z_factor:g}">{_MINMAX}</rasterrenderer>')


def paletted_renderer(band: int, classes) -> str:
    """Class legend. ``classes``: iterable of (value, hex colour, label)."""
    entries = "".join(
        f'<paletteEntry value="{v}" color="{c.lower()}" label={quoteattr(lbl)} alpha="255"/>'
        for v, c, lbl in classes)
    return (f'<rasterrenderer type="paletted" band="{band}" opacity="1" alphaBand="-1" nodataColor="">'
            f'{_MINMAX}<colorPalette>{entries}</colorPalette></rasterrenderer>')


def pseudocolor_renderer(band: int, vmin: float, vmax: float, colors=VIRIDIS) -> str:
    """Continuous colour ramp from ``vmin`` to ``vmax`` (values outside are clamped)."""
    n = len(colors)
    items = "".join(
        f'<item value="{vmin + (vmax - vmin) * i / (n - 1):.6g}" color="{c}" '
        f'label="{vmin + (vmax - vmin) * i / (n - 1):.3g}" alpha="255"/>'
        for i, c in enumerate(colors))
    return (f'<rasterrenderer type="singlebandpseudocolor" band="{band}" opacity="1" alphaBand="-1" '
            f'classificationMin="{vmin:.6g}" classificationMax="{vmax:.6g}" nodataColor="">{_MINMAX}'
            f'<rastershader><colorrampshader colorRampType="INTERPOLATED" labelPrecision="3" clip="0" '
            f'minimumValue="{vmin:.6g}" maximumValue="{vmax:.6g}" classificationMode="1">{items}'
            f'</colorrampshader></rastershader></rasterrenderer>')


def qml(renderer: str, resample: str = "nearestNeighbour") -> str:
    """A complete ``.qml`` layer-style document for one renderer."""
    return ("<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>\n"
            '<qgis version="3.44.0" styleCategories="AllStyleCategories">\n  '
            + _PIPE.format(renderer=renderer, resample=resample)
            + "\n  <blendMode>0</blendMode>\n</qgis>\n")


# ------------------------------------------------------------------- views

def _sample(src, band, max_dim=1024):
    """Read a band decimated to at most ``max_dim`` px per side (fast on big cubes)."""
    step = max(1, int(np.ceil(max(src.height, src.width) / max_dim)))
    shape = (max(1, src.height // step), max(1, src.width // step))
    a = src.read(band, out_shape=shape).astype("float64")
    if src.nodata is not None and not np.isnan(src.nodata):
        a[a == src.nodata] = np.nan
    return a


def _percentiles(src, band, lo=2, hi=98):
    a = _sample(src, band)
    a = a[np.isfinite(a)]
    if not a.size:
        return 0.0, 1.0
    p = np.percentile(a, [lo, hi])
    return float(p[0]), float(p[1]) if p[1] > p[0] else float(p[0]) + 1.0


def cube_views(path) -> list:
    """Views for a cube, top of the QGIS layer list first.

    Each view is ``{"name", "renderer", "visible", "resample"}``. Order:
    class legends (hidden), natural colour (shown), hillshade (shown).
    A cube with none of these gets one colour-ramp view of band 1.
    """
    path = Path(path)
    with rasterio.open(path) as src:
        names = list(src.descriptions)
        if not any(names):
            names = [f"band_{i}" for i in range(1, src.count + 1)]
        mission = _single_mission(path)
        resolved = resolve_bands(names, mission)
        index = {(m, code): i for i, (m, code, _, _) in enumerate(resolved, start=1)}

        classes, rgb, relief = [], [], []
        for i, (m, code, kind, _) in enumerate(resolved, start=1):
            if kind in ("scl", "categorical"):
                classes.append(_class_view(src, i, m, code, kind, names[i - 1]))
            elif kind == "elevation":
                relief.append({"name": f"{names[i - 1]} hillshade", "renderer": hillshade_renderer(i),
                               "visible": True, "resample": "bilinear"})
        for m in dict.fromkeys(m for m, *_ in resolved if m in TRUE_COLOR):
            idx = [index.get((m, code)) for code in TRUE_COLOR[m]]
            if None in idx:
                continue
            stats = [_percentiles(src, b) for b in idx]
            rgb.append({"name": f"{m} natural colour",
                        "renderer": rgb_renderer(idx, [s[0] for s in stats], [s[1] for s in stats]),
                        "visible": True, "resample": "bilinear"})

        views = classes + rgb + relief
        if not rgb and not relief and classes:
            classes[0]["visible"] = True
        if not views:
            lo, hi = _percentiles(src, 1)
            views = [{"name": names[0], "renderer": pseudocolor_renderer(1, lo, hi),
                      "visible": True, "resample": "bilinear"}]
    return views


def _class_view(src, band, mission, code, kind, name):
    a = _sample(src, band, max_dim=2048)
    present = sorted(int(v) for v in np.unique(a[np.isfinite(a)]))
    legend = legend_for(mission, code, kind) or {}
    entries = []
    for j, v in enumerate(present):
        label, color = legend.get(v, (f"class {v}", FALLBACK_COLORS[j % len(FALLBACK_COLORS)]))
        entries.append((v, color, f"{v} {label}"))
    return {"name": f"{name} classes", "renderer": paletted_renderer(band, entries),
            "visible": False, "resample": "nearestNeighbour"}


def _single_mission(path: Path):
    """``Sentinel-2_full_size.tiff`` -> ``"Sentinel-2"`` (bands carry no prefix there)."""
    stem = path.name
    for suffix in ("_full_size.tiff", "_full_size.tif"):
        if stem.endswith(suffix):
            return stem[: -len(suffix)]
    return None


# ----------------------------------------------------------------- writing

def _srs_xml(crs) -> str:
    # QGIS ignores an <authid> on its own for the project CRS; it needs the WKT.
    from pyproj import CRS

    import warnings

    p = CRS.from_user_input(crs.to_wkt())
    epsg = p.to_epsg()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # pyproj warns that PROJ strings lose detail
        proj4 = p.to_proj4()
    authid = f"<authid>EPSG:{epsg}</authid><srid>{epsg}</srid>" if epsg else ""
    return (f'<spatialrefsys nativeFormat="Wkt"><wkt>{escape(p.to_wkt())}</wkt>'
            f"<proj4>{escape(proj4)}</proj4>{authid}"
            f"<description>{escape(p.name)}</description></spatialrefsys>")


def write_project(qgs_path, raster_path, views) -> Path:
    """Write a ``.qgs`` project that opens ``raster_path`` once per view."""
    qgs_path, raster_path = Path(qgs_path), Path(raster_path)
    with rasterio.open(raster_path) as src:
        crs, b = src.crs, src.bounds
    srs = _srs_xml(crs)
    try:
        source = raster_path.resolve().relative_to(qgs_path.resolve().parent).as_posix()
        source = "./" + source
    except ValueError:
        source = raster_path.resolve().as_posix()
    extent = (f"<xmin>{b.left}</xmin><ymin>{b.bottom}</ymin>"
              f"<xmax>{b.right}</xmax><ymax>{b.top}</ymax>")

    tree, layers, order = [], [], []
    for v in views:
        lid = f"layer_{uuid.uuid4().hex[:12]}"
        name = quoteattr(v["name"])
        checked = "Qt::Checked" if v["visible"] else "Qt::Unchecked"
        tree.append(f'<layer-tree-layer id="{lid}" name={name} source="{escape(source)}" '
                    f'providerKey="gdal" checked="{checked}" expanded="1"/>')
        order.append(f'<layer id="{lid}"/>')
        layers.append(
            f'<maplayer type="raster" styleCategories="AllStyleCategories">'
            f"<extent>{extent}</extent><id>{lid}</id><datasource>{escape(source)}</datasource>"
            f"<layername>{escape(v['name'])}</layername><srs>{srs}</srs><provider>gdal</provider>"
            + _PIPE.format(renderer=v["renderer"], resample=v.get("resample", "nearestNeighbour"))
            + "<blendMode>0</blendMode></maplayer>")

    doc = f"""<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.44.0" projectname={quoteattr(raster_path.stem)}>
  <title>{escape(raster_path.stem)}</title>
  <projectCrs>{srs}</projectCrs>
  <layer-tree-group>{''.join(tree)}</layer-tree-group>
  <mapcanvas name="theMapCanvas"><units>meters</units><extent>{extent}</extent><rotation>0</rotation><destinationsrs>{srs}</destinationsrs></mapcanvas>
  <projectlayers>{''.join(layers)}</projectlayers>
  <layerorder>{''.join(order)}</layerorder>
  <properties><Paths><Absolute type="bool">false</Absolute></Paths><SpatialRefSys><ProjectionsEnabled type="int">1</ProjectionsEnabled></SpatialRefSys></properties>
  <ProjectViewSettings rotation="0" UseProjectScales="0"><Scales/><DefaultViewExtent xmin="{b.left}" ymin="{b.bottom}" xmax="{b.right}" ymax="{b.top}">{srs}</DefaultViewExtent></ProjectViewSettings>
</qgis>
"""
    qgs_path.write_text(doc)
    return qgs_path


def style_cube(path, views=None) -> dict:
    """Write ``<stem>.qml`` (main view) and ``<stem>.qgs`` (all views) next to ``path``.

    Returns ``{"project", "qml", "views"}``. Open the project in QGIS to
    get every view; open the GeoTIFF alone to get just the main one.
    """
    path = Path(path)
    views = views or cube_views(path)
    main = next((v for v in views if v["visible"]), views[0])
    qml_path = path.with_suffix(".qml")
    qml_path.write_text(qml(main["renderer"], main.get("resample", "nearestNeighbour")))
    project = write_project(path.with_suffix(".qgs"), path, views)
    return {"project": project, "qml": qml_path, "views": [v["name"] for v in views]}
