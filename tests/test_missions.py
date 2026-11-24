"""Structural tests on MISSION_PROFILES -- guards against regressions in
the mission registry."""
import pytest

from geoai_datacubes.fetch import MISSION_PROFILES

# Missions we expect to be first-class citizens in the registry. If a
# rename or removal happens this list catches it.
_EXPECTED_MISSIONS = (
    "Sentinel-2", "Sentinel-2-L1C",
    "Sentinel-1",
    "Landsat",
    "Copernicus-DEM", "Copernicus-DEM-90", "ALOS-DEM",
    "ArcticDEM",
    "ESA-WorldCover",
    "NAIP",
    "MODIS_SR", "MODIS_LST",
    "HLS_S30", "HLS_L30",
    "3DEP",
    "KyFromAbove-DEM",
    "JRC-GSW",
    "ALOS-PALSAR", "ALOS-FNF",
    "Hansen-GFC",
    "USDA-CDL", "LCMAP-CONUS", "IO-LULC", "ESA-CCI-LC",
    "Chloris-Biomass",
    "Dynamic-World",
    "JRC-GFC2020",
    "NISAR-L",
    "ICESat-2-ATL03",
    "ICESat-2-ATL06",
    "ICESat-2-ATL08",
    "ICESat-2-ATL13",
    "SWOT-HR",
    "CryoSat-RDEFT4",
    "PlanetScope-4b", "PlanetScope-8b",
    "GEDI-L4B", "GEDI-L4A",
    "SMAP-L3",
    "GEBCO-2024",
    "Sentinel-5P-NO2",                            # v0.2 preview: TROPOMI NO2 via tracks flow
    "Sentinel-5P",                                # documented stub (remaining unwired gases)
)


@pytest.mark.parametrize("mission", _EXPECTED_MISSIONS)
def test_mission_in_registry(mission):
    assert mission in MISSION_PROFILES, f"missing from MISSION_PROFILES: {mission}"


def test_mission_count_at_least_26():
    # 26 user-facing + Landsat-8 / Landsat-9 aliases of Landsat = 28 in the
    # raw dict. Accept >= 26 to leave room for future additions without
    # forcing this test to flap.
    assert len(MISSION_PROFILES) >= 26


@pytest.mark.parametrize("mission", _EXPECTED_MISSIONS)
def test_mission_has_required_keys(mission):
    profile = MISSION_PROFILES[mission]
    for key in ("default_bands", "extra_bands", "band_meta", "providers"):
        assert key in profile, f"{mission}: missing key {key!r}"


def test_band_meta_entries_have_kind_and_norm():
    # Every band that appears in any mission's band_meta should declare
    # at least a 'kind' and a 'norm'.
    for mission, profile in MISSION_PROFILES.items():
        band_meta = profile.get("band_meta", {}) or {}
        for band, meta in band_meta.items():
            assert "kind" in meta, f"{mission}/{band}: band_meta missing 'kind'"
            assert "norm" in meta, f"{mission}/{band}: band_meta missing 'norm'"


def test_stub_missions_have_no_providers():
    # Sentinel-5P is the only remaining documented stub: registered in
    # MISSION_PROFILES for visibility / docs but not yet wired into the
    # PROVIDER_AUTO router. Its providers dict should be empty OR it
    # should not appear in PROVIDER_AUTO. GEDI-L4B was moved out when
    # it was wired via the earthdata `raster_per_band` flow; GEBCO
    # (renamed `GEBCO-2024` on the same commit) was moved out when it
    # was wired via `direct_http` against BODC/CEDA's per-tile GeoTIFFs.
    from geoai_datacubes.fetch.fetch_data import PROVIDER_AUTO
    for stub in ("Sentinel-5P",):
        # No router entry == cannot be fetched (which is the contract).
        assert stub not in PROVIDER_AUTO or not PROVIDER_AUTO[stub]


# ---- ALOS-DEM and ESA-CCI-LC (issue #7) ----

def test_new_pc_missions_are_auto_routed():
    from geoai_datacubes.fetch.fetch_data import PROVIDER_AUTO
    for mission in ("ALOS-DEM", "ESA-CCI-LC"):
        assert PROVIDER_AUTO[mission] == "planetary_computer"
        assert "planetary_computer" in MISSION_PROFILES[mission]["providers"]


def test_esa_cci_lc_bands_resample_nearest():
    # Class codes and QA counts must never be averaged by bilinear resampling.
    from rasterio.warp import Resampling
    from geoai_datacubes.fetch.fetch_data import _resampling_for_band
    profile = MISSION_PROFILES["ESA-CCI-LC"]
    for band in profile["providers"]["planetary_computer"]["asset_map"]:
        assert _resampling_for_band(band, None, profile) == Resampling.nearest


def test_esa_cci_lc_one_hot_covers_all_lccs_classes():
    classes = MISSION_PROFILES["ESA-CCI-LC"]["band_meta"]["LCCS"]["norm"][1]
    assert len(classes) == len(set(classes)) == 37
    assert 0 not in classes          # 0 is no-data
    assert {10, 190, 210, 220} <= set(classes)


def test_esa_cci_lc_processed_flag_is_opt_in():
    profile = MISSION_PROFILES["ESA-CCI-LC"]
    assert "processed_flag" not in profile["default_bands"] + profile["extra_bands"]
    assert "processed_flag" in profile["providers"]["planetary_computer"]["asset_map"]


def test_alos_dem_is_static_elevation():
    profile = MISSION_PROFILES["ALOS-DEM"]
    assert profile["static"] is True
    assert profile["band_meta"]["DEM"]["kind"] == "elevation"
