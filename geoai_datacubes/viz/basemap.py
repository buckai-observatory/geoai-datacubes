"""Basemap helper for the notebooks (needs the optional ``contextily`` package).

The default is OpenStreetMap, which needs no key but blocks clients that do
not send an identifying ``User-Agent`` (the response is a "403 Access
blocked" tile image, not an exception). This helper sends a descriptive
``User-Agent`` as OSM's tile usage policy asks. CARTO basemaps are available
as an alternative and require a free API key (https://carto.com/basemaps/apikey/).
"""

from __future__ import annotations

import os

CARTO_KEY_ENV = "CARTO_API_KEY"
CARTO_KEY_URL = "https://carto.com/basemaps/apikey/"


def _user_agent() -> str:
    try:
        from .. import __version__
    except Exception:
        __version__ = "unknown"
    return (f"geoai-datacubes/{__version__} "
            "(+https://github.com/buckai-observatory/geoai-datacubes)")


def add_basemap(ax, crs="EPSG:4326", provider="osm", api_key=None,
                attribution_size=6):
    """Draw a basemap under ``ax``; return True if one was drawn.

    Parameters
    ----------
    provider : {"osm", "carto"} or a contextily/xyzservices tile provider
        ``"osm"`` (default) needs no key. ``"carto"`` uses CartoDB.Positron
        and needs a key, passed as ``api_key`` or set in the
        ``CARTO_API_KEY`` environment variable; without one this falls back
        to OSM and prints how to get a key.

    Never raises: if ``contextily`` is missing or the tiles cannot be fetched
    the axes are left unchanged and False is returned.
    """
    try:
        import contextily as cx
    except ImportError:
        print("(contextily not installed; no basemap)")
        return False

    if isinstance(provider, str):
        name = provider.lower()
        if name == "carto":
            key = api_key or os.environ.get(CARTO_KEY_ENV)
            if key:
                source = cx.providers.CartoDB.Positron(apikey=key)
            else:
                print(f"(CARTO needs an API key: get one at {CARTO_KEY_URL}, then "
                      f"pass api_key=... or set {CARTO_KEY_ENV}; using OpenStreetMap)")
                source = cx.providers.OpenStreetMap.Mapnik
        elif name == "osm":
            source = cx.providers.OpenStreetMap.Mapnik
        else:
            raise ValueError(f"provider must be 'osm', 'carto' or a tile provider, got {provider!r}")
    else:
        source = provider

    kwargs = dict(crs=crs, source=source, attribution_size=attribution_size)
    try:
        try:
            cx.add_basemap(ax, headers={"User-Agent": _user_agent()}, **kwargs)
        except TypeError:  # older contextily has no ``headers`` argument
            cx.add_basemap(ax, **kwargs)
    except Exception as e:
        print(f"(basemap unavailable: {type(e).__name__}: {e})")
        return False
    return True
