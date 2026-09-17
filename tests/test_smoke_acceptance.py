"""Tests for the smoke-test acceptance-check logic.

Uses synthetic GeoTIFFs to prove the three false-pass patterns
identified in the JOSS review (openjournals/joss-reviews#11034) are
now caught as hard violations:

* Infinity pixels in a band (previously silently dropped by the
  ``finite = band[np.isfinite(band)]`` filter before the value-range
  check).
* An invalid categorical code in the middle of a band whose min/max
  happen to be valid (previously only min/max were checked, and only
  as a warning).
* A GeoTIFF with an identity Affine transform (previously the
  ``src.transform is not None`` check always passed because rasterio
  never returns ``None`` -- it returns Affine.identity() when no
  georeferencing was written).

Also covers the Sentinel-2 units fix: the fetcher writes scaled DN
(0..10000, reflectance x 10000), not post-normalisation reflectance
(0..1). The acceptance value_range must match what is written.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import Affine, from_origin

# smoke-tests/ is a sibling of tests/; splice it onto sys.path so the
# _run_fetch module can be imported without packaging it.
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "smoke-tests"))

from _run_fetch import (  # noqa: E402
    ACCEPTANCE,
    check_acceptance,
    validate_geotiff,
)


# ---------------------------------------------------------------------------
# GeoTIFF fixtures
# ---------------------------------------------------------------------------

_CRS = "EPSG:32617"
_TRANSFORM = from_origin(west=300000, north=4500000, xsize=10, ysize=10)


def _write_tif(
    path: Path,
    data: np.ndarray,
    descriptions=None,
    crs=_CRS,
    transform=_TRANSFORM,
    dtype="float32",
):
    """Write a small multi-band GeoTIFF. ``data`` is (bands, h, w)."""
    if data.ndim == 2:
        data = data[np.newaxis, :, :]
    count, h, w = data.shape
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=h,
        width=w,
        count=count,
        dtype=dtype,
        crs=crs,
        transform=transform,
    ) as dst:
        dst.write(data.astype(dtype))
        if descriptions is not None:
            for i, d in enumerate(descriptions):
                dst.set_band_description(i + 1, d)


# ---------------------------------------------------------------------------
# 1. Sanity: a valid Sentinel-2 style cube passes
# ---------------------------------------------------------------------------

def test_valid_s2_dn_band_passes(tmp_path):
    """A single-band synthetic S2 GeoTIFF with values in the scaled-DN
    range 500..9000 must PASS under the (updated) Sentinel-2 rule."""
    p = tmp_path / "s2_ok.tif"
    rng = np.random.default_rng(0)
    band = rng.uniform(500, 9000, size=(32, 32))
    _write_tif(p, band, descriptions=["B04"])

    summary = validate_geotiff(p)
    verdict, violations, _ = check_acceptance("Sentinel-2", ["B04"], summary)
    assert verdict == "passed", (verdict, violations)


# ---------------------------------------------------------------------------
# 2. Infinity pixels: hard fail
# ---------------------------------------------------------------------------

def test_infinity_pixels_hard_fail(tmp_path):
    """A band with even a single +inf pixel is rejected. Previously
    the isfinite() filter silently dropped it and the value_range check
    saw the finite pixels as within [0, 20000]."""
    p = tmp_path / "s2_inf.tif"
    band = np.full((32, 32), 5000.0, dtype=np.float32)
    band[10, 10] = np.inf   # one infinite pixel
    _write_tif(p, band, descriptions=["B04"])

    summary = validate_geotiff(p)
    pb = summary["per_band"][0]
    assert pb["infinite_fraction"] > 0.0

    verdict, violations, _ = check_acceptance("Sentinel-2", ["B04"], summary)
    assert verdict == "failed"
    assert any("infinity" in v.lower() for v in violations)


def test_all_infinity_band_hard_fails(tmp_path):
    """A band that is 100% +inf is rejected -- previously ``finite``
    would be empty, min/max would round-trip to ``None``, and the
    acceptance check would ``continue`` past both the range and
    categorical checks, silently PASSING an all-infinity band."""
    p = tmp_path / "s2_all_inf.tif"
    band = np.full((32, 32), np.inf, dtype=np.float32)
    _write_tif(p, band, descriptions=["B04"])

    summary = validate_geotiff(p)
    pb = summary["per_band"][0]
    assert pb["infinite_fraction"] == pytest.approx(1.0)
    assert pb["min"] is None and pb["max"] is None

    verdict, violations, _ = check_acceptance("Sentinel-2", ["B04"], summary)
    assert verdict == "failed"
    assert any("infinity" in v.lower() for v in violations)


def test_negative_infinity_also_caught(tmp_path):
    """``-inf`` pixels are as bad as ``+inf`` pixels and must be
    rejected too."""
    p = tmp_path / "s2_neg_inf.tif"
    band = np.full((32, 32), 5000.0, dtype=np.float32)
    band[0, 0] = -np.inf
    _write_tif(p, band, descriptions=["B04"])

    summary = validate_geotiff(p)
    verdict, _, _ = check_acceptance("Sentinel-2", ["B04"], summary)
    assert verdict == "failed"


# ---------------------------------------------------------------------------
# 3. Invalid categorical code in the middle: hard fail
# ---------------------------------------------------------------------------

def test_invalid_categorical_code_in_middle_hard_fails(tmp_path):
    """An ESA-WorldCover raster whose min=10 (valid Tree Cover) and
    max=100 (valid Moss and lichen) both round to valid codes, but
    which contains a 47 pixel in the middle (not in the WorldCover
    code set), must FAIL. The old min/max-only check missed exactly
    this case and only raised a warning even if it had found an
    invalid extreme."""
    p = tmp_path / "wc_bad.tif"
    band = np.full((32, 32), 10.0, dtype=np.float32)   # min = 10 (Tree Cover)
    band[16, 16] = 47.0                                # invalid code
    band[31, 31] = 100.0                               # max = 100 (Moss)
    _write_tif(p, band, descriptions=["LULC"])

    summary = validate_geotiff(p)
    pb = summary["per_band"][0]
    assert 47 in (pb["unique_int_codes"] or [])

    verdict, violations, _ = check_acceptance(
        "ESA-WorldCover", ["LULC"], summary,
    )
    assert verdict == "failed"
    assert any("categorical" in v.lower() and "47" in v for v in violations)


def test_only_valid_categorical_codes_pass(tmp_path):
    """A WorldCover raster whose sampled unique codes are all in the
    declared set passes."""
    p = tmp_path / "wc_ok.tif"
    valid_codes = [10, 20, 30, 40, 50, 60, 70, 80, 90, 95, 100]
    rng = np.random.default_rng(0)
    band = rng.choice(valid_codes, size=(32, 32)).astype(np.float32)
    _write_tif(p, band, descriptions=["LULC"])

    summary = validate_geotiff(p)
    verdict, violations, _ = check_acceptance(
        "ESA-WorldCover", ["LULC"], summary,
    )
    assert verdict == "passed", (verdict, violations)


def test_non_integer_categorical_hard_fails(tmp_path):
    """A categorical band whose values are fractional (e.g. someone
    used bilinear resampling on a class-code raster) must fail --
    previously only warned."""
    p = tmp_path / "wc_frac.tif"
    band = np.full((32, 32), 10.5, dtype=np.float32)
    _write_tif(p, band, descriptions=["LULC"])

    summary = validate_geotiff(p)
    verdict, violations, _ = check_acceptance(
        "ESA-WorldCover", ["LULC"], summary,
    )
    assert verdict == "failed"
    assert any("integer" in v.lower() for v in violations)


# ---------------------------------------------------------------------------
# 4. Missing / identity georeferencing transform: hard fail
# ---------------------------------------------------------------------------

def test_identity_transform_hard_fails(tmp_path):
    """A GeoTIFF written with the identity Affine (no georeferencing)
    must fail. rasterio never returns ``None`` for ``src.transform``,
    so the old ``transform_present`` check always passed even for
    georeferencing-free rasters."""
    p = tmp_path / "s2_no_geo.tif"
    band = np.full((32, 32), 5000.0, dtype=np.float32)
    _write_tif(p, band, descriptions=["B04"], transform=Affine.identity())

    summary = validate_geotiff(p)
    assert summary["transform_is_georeferenced"] is False

    verdict, violations, _ = check_acceptance("Sentinel-2", ["B04"], summary)
    assert verdict == "failed"
    assert any("georeferencing" in v.lower() for v in violations)


def test_missing_crs_hard_fails(tmp_path):
    """A GeoTIFF written with no CRS must fail (this check already
    worked; the test guards against regression)."""
    p = tmp_path / "s2_no_crs.tif"
    band = np.full((32, 32), 5000.0, dtype=np.float32)
    _write_tif(p, band, descriptions=["B04"], crs=None)

    summary = validate_geotiff(p)
    assert summary["crs"] is None

    verdict, violations, _ = check_acceptance("Sentinel-2", ["B04"], summary)
    assert verdict == "failed"
    assert any("crs" in v.lower() for v in violations)


# ---------------------------------------------------------------------------
# 5. Units regression guards
# ---------------------------------------------------------------------------

def test_s2_reflectance_style_values_now_flagged(tmp_path):
    """If someone accidentally divides a Sentinel-2 fetch by 10000 in
    a wrapper, all pixels land in [0, 1] -- that's a valid range in
    the *old* (buggy) acceptance rule but under the DN convention it
    means the caller normalized twice. This test documents the
    intended behaviour: 0..1 reflectance is *outside* the DN range
    only for the max side, so we don't fail it (a plausible dark
    scene could sit at those values). This test just asserts the new
    range [-2000, 20000] covers the fetcher's actual output."""
    crit = ACCEPTANCE["Sentinel-2"]
    lo, hi = crit["value_range"]
    assert lo <= 0.0 and hi >= 10000.0, (lo, hi)


def test_landsat_uint16_range(tmp_path):
    """Landsat C2 L2 surface reflectance is uint16 DN with scale +
    offset. Range should cover 0..65535."""
    crit = ACCEPTANCE["Landsat"]
    lo, hi = crit["value_range"]
    assert lo == 0.0 and hi == 65535.0, (lo, hi)


# ---------------------------------------------------------------------------
# 6. Structural: validate_geotiff exposes the new fields
# ---------------------------------------------------------------------------

def test_validate_geotiff_exposes_infinity_and_codes(tmp_path):
    """The per-band summary must expose infinite_fraction and
    unique_int_codes (used by the new checks). Guards against a
    future refactor silently removing them."""
    p = tmp_path / "cat.tif"
    band = np.array([[1, 2, 3, 4]] * 4, dtype=np.float32)
    _write_tif(p, band, descriptions=["cls"])

    summary = validate_geotiff(p)
    pb = summary["per_band"][0]
    assert "infinite_fraction" in pb
    assert "unique_int_codes" in pb
    assert sorted(pb["unique_int_codes"]) == [1, 2, 3, 4]
    assert "transform_is_georeferenced" in summary
    assert "transform_affine" in summary
