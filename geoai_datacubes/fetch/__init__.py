"""Data acquisition: download raw imagery from public and commercial sources.

The public API surface is small. Most users only need:

* :func:`resolve_aoi` -- parse one of four AOI input formats to a WGS84 bbox
* :func:`fetch_sentinel_data` -- the unified mission-agnostic dispatcher
* :data:`MISSION_PROFILES` / :func:`get_profile` -- inspect what is available

Sentinel Hub OAuth credentials are read from a ``.env`` via
:func:`config.get_config_from_env`; the Planet Orders API uses
``PL_API_KEY`` from the same place.

To add a new satellite that is served by an existing STAC catalog
(Earth Search or Microsoft Planetary Computer), add an entry to
:data:`MISSION_PROFILES` (in ``missions.py``) and a routing line to
``PROVIDER_AUTO`` (in ``fetch_data.py``). No further changes needed
for the generic STAC + COG missions -- the dispatcher handles
mosaicking, NaN edges, categorical-band nearest-neighbour resampling,
cloud filtering, and band selection automatically.
"""

from .aoi import resolve_aoi
from .missions import (
    MISSION_PROFILES,
    get_profile,
    get_provider_config,
    set_arcticdem_resolution,
)
from .fetch_data import (
    fetch_sentinel_data,
    fetch_earthsearch,
    fetch_planetary_computer,
    fetch_sentinelhub,
    fetch_planet,
)
from .parallel_fetch import fetch_many_in_parallel

__all__ = [
    "resolve_aoi",
    "MISSION_PROFILES",
    "get_profile",
    "get_provider_config",
    "set_arcticdem_resolution",
    "fetch_sentinel_data",
    "fetch_earthsearch",
    "fetch_planetary_computer",
    "fetch_sentinelhub",
    "fetch_planet",
    "fetch_many_in_parallel",
]
