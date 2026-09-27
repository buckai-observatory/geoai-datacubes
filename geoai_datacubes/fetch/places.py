"""Turn a place name, an alias, or a "lat, lon" string into an AOI bbox.

Three kinds of input, tried in this order:

1. ``"lat, lon"`` -- used as given, no network call.
2. An alias from :data:`GAZETTEER` or from a local places file (see
   :func:`load_places`). An alias maps either to coordinates or to a
   clearer query for the geocoder ("Lipari" -> "Lipari, Sicily, Italy").
3. Anything else goes to OpenStreetMap's Nominatim geocoder through
   ``geopy`` (``pip install geoai-datacubes[demo]``).

Local places file: ``.geoai-places.json`` in the current directory, or
the path in ``$GEOAI_PLACES``. Format::

    {"here": {"lat": 40.00604, "lon": -83.03490, "name": "Energy Advancement and Innovation Center"},
     "catalina": "Santa Catalina Island, California, USA"}
"""
from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path

# Short names the geocoder gets wrong or can't resolve on their own.
GAZETTEER = {
    "lipari": "Lipari, Sicily, Italy",
    "vulcano": "Vulcano, Sicily, Italy",
    "salina": "Salina, Sicily, Italy",
    "stromboli": "Stromboli, Sicily, Italy",
    "panarea": "Panarea, Sicily, Italy",
    "filicudi": "Filicudi, Sicily, Italy",
    "alicudi": "Alicudi, Sicily, Italy",
    "favignana": "Favignana, Sicily, Italy",
    "levanzo": "Levanzo, Sicily, Italy",
    "marettimo": "Marettimo, Sicily, Italy",
    "capri": "Capri, Campania, Italy",
    "procida": "Procida, Campania, Italy",
    "ischia": "Ischia, Campania, Italy",
    "catalina": "Santa Catalina Island, California, USA",
}

_LATLON = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*[, ]\s*(-?\d+(?:\.\d+)?)\s*$")
_USER_AGENT = "geoai-datacubes"


def load_places(path=None) -> dict:
    """Aliases from a local places file, keys lower-cased. Missing file -> {}."""
    path = Path(path or os.environ.get("GEOAI_PLACES") or ".geoai-places.json")
    if not path.is_file():
        return {}
    return {k.strip().lower(): v for k, v in json.loads(path.read_text()).items()}


def bbox_around(lat: float, lon: float, radius_km: float) -> list:
    """Square [lon_min, lat_min, lon_max, lat_max] of half-width radius_km.

    Longitude span is widened by 1/cos(lat) so the box is square on the
    ground rather than squeezed east-west away from the equator.
    """
    dlat = radius_km / 111.32
    dlon = radius_km / (111.32 * max(math.cos(math.radians(lat)), 1e-6))
    return [lon - dlon, lat - dlat, lon + dlon, lat + dlat]


def locate(place: str, radius_km: float = 2.0, places_file=None) -> dict:
    """Resolve ``place`` to ``{lat, lon, bbox, name, source}``.

    ``source`` is ``"coordinates"``, ``"alias"`` or ``"geocoder"`` so a
    caller can show how the place was matched.
    """
    m = _LATLON.match(place)
    if m:
        lat, lon = float(m.group(1)), float(m.group(2))
        return _result(lat, lon, radius_km, f"{lat:.5f}, {lon:.5f}", "coordinates")

    key = place.strip().lower()
    entry = load_places(places_file).get(key, GAZETTEER.get(key))
    if isinstance(entry, dict):
        return _result(float(entry["lat"]), float(entry["lon"]), radius_km,
                       entry.get("name", place), "alias")
    query = entry or place

    try:
        from geopy.geocoders import Nominatim
    except ImportError as e:
        raise ImportError(
            "Place-name lookup needs geopy: pip install 'geoai-datacubes[demo]'. "
            "Or pass coordinates as 'lat, lon'."
        ) from e
    loc = Nominatim(user_agent=_USER_AGENT).geocode(query)
    if loc is None:
        raise ValueError(f"Could not find {query!r}. Try a fuller name or 'lat, lon'.")
    return _result(loc.latitude, loc.longitude, radius_km, loc.address,
                   "alias" if entry else "geocoder")


def _result(lat, lon, radius_km, name, source):
    return {"lat": lat, "lon": lon, "radius_km": radius_km,
            "bbox": bbox_around(lat, lon, radius_km), "name": name, "source": source}
