"""Guard: the fetch + preprocessing surfaces must import cleanly WITHOUT
`torch` installed. Regression from a JOSS-review comment (Aug 2026) that
called out `torch>=2.0` being a hard core dep despite most users of the
fetch API never touching PyTorch. See PR touching pyproject.toml,
geoai_datacubes/preprocessing/__init__.py, and this test.
"""
from __future__ import annotations

import importlib
import importlib.abc
import subprocess
import sys
import textwrap

import pytest


class _BlockTorch(importlib.abc.MetaPathFinder):
    """Meta-path finder that makes `import torch` (and torchvision) raise
    ImportError, without touching anything else. Used to simulate a
    torch-less environment inside a single test process."""

    def find_spec(self, name, path=None, target=None):
        if name == "torch" or name.startswith("torch."):
            raise ImportError(
                f"BLOCKED (simulating [ml] extra not installed): {name}")
        if name == "torchvision" or name.startswith("torchvision."):
            raise ImportError(
                f"BLOCKED (simulating [ml] extra not installed): {name}")
        return None


@pytest.fixture()
def torchless(monkeypatch):
    # Purge any already-imported torch (and our own top-level modules)
    # so a fresh in-fixture import re-triggers the finder.
    for mod in list(sys.modules):
        if (mod == "torch" or mod.startswith("torch.")
                or mod == "torchvision" or mod == "skimage"
                or mod.startswith("skimage.")
                or mod.startswith("geoai_datacubes")):
            monkeypatch.delitem(sys.modules, mod, raising=False)
    blocker = _BlockTorch()
    monkeypatch.setattr(sys, "meta_path", [blocker, *sys.meta_path])
    yield


def test_fetch_import_works_without_torch(torchless):
    from geoai_datacubes.fetch import fetch_sentinel_data       # noqa: F401
    assert "torch" not in sys.modules


def test_preprocessing_core_surface_works_without_torch(torchless):
    from geoai_datacubes.preprocessing import (
        fuse_response_tiffs, tile_geotiff, compute_ndvi,
    )  # noqa: F401
    assert "torch" not in sys.modules


def test_lazy_tile_dataset_stub_raises_actionable_error(torchless):
    from geoai_datacubes.preprocessing import LazyTileDataset
    with pytest.raises(ImportError, match=r"\[ml\] extra"):
        LazyTileDataset(cube_path="x", feature_bands=[], tile_size=64)


def test_geotiff_to_zarr_stub_raises_actionable_error(torchless):
    from geoai_datacubes.preprocessing import geotiff_to_zarr
    with pytest.raises(ImportError, match=r"\[ml\] extra"):
        geotiff_to_zarr("x", "y")


def test_true_import_from_subprocess_without_torch():
    """The subprocess-based version of the above -- runs in a fresh
    interpreter with torch and torchvision hidden via a PYTHONPATH shim,
    so it's not fooled by any already-loaded torch state in the test
    process. Belt-and-braces guard against the surface silently
    re-acquiring a hard torch dep."""
    script = textwrap.dedent("""
        import sys, importlib.abc

        class _B(importlib.abc.MetaPathFinder):
            def find_spec(self, name, path=None, target=None):
                if name == 'torch' or name.startswith('torch.'):
                    raise ImportError('torch blocked')
                if name == 'torchvision':
                    raise ImportError('torchvision blocked')
                return None
        sys.meta_path.insert(0, _B())

        from geoai_datacubes.fetch import fetch_sentinel_data
        from geoai_datacubes.preprocessing import (
            fuse_response_tiffs, tile_geotiff, compute_ndvi,
        )
        assert 'torch' not in sys.modules
        print('OK')
    """)
    r = subprocess.run([sys.executable, "-c", script],
                       capture_output=True, text=True)
    assert r.returncode == 0, (
        f"subprocess failed:\nSTDOUT: {r.stdout}\nSTDERR: {r.stderr}")
    assert r.stdout.strip() == "OK", r.stdout
