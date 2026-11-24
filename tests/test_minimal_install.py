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
        # A genuinely absent package raises ModuleNotFoundError with .name
        # set; the lazy loader relies on that to tell "torch is not
        # installed" apart from any other import failure.
        if name == "torch" or name.startswith("torch."):
            raise ModuleNotFoundError(
                f"BLOCKED (simulating [ml] extra not installed): {name}", name=name)
        if name == "torchvision" or name.startswith("torchvision."):
            raise ModuleNotFoundError(
                f"BLOCKED (simulating [ml] extra not installed): {name}", name=name)
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


def test_preprocessing_import_does_not_load_torch():
    """Data-prep imports must not pull in torch even when it is installed.

    Keeps fetch / fuse / tile notebooks independent of the PyTorch native
    stack; torch loads only when LazyTileDataset / geotiff_to_zarr is used.
    """
    code = textwrap.dedent("""
        import sys
        import geoai_datacubes.fetch
        from geoai_datacubes.preprocessing import fuse_response_tiffs, tile_geotiff
        assert "torch" not in sys.modules, "torch imported by data-prep imports"
    """)
    out = subprocess.run([sys.executable, "-c", code],
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stderr


def test_lazy_exports_are_visible_to_static_analysis():
    """The API-reference build (quartodoc/griffe) reads the source without
    running it, so the lazily loaded names must also be imported under
    ``TYPE_CHECKING``. Without that the docs site build fails with
    "Cannot find an object named: LazyTileDataset"."""
    import ast
    from pathlib import Path

    import geoai_datacubes.preprocessing as pre

    tree = ast.parse(Path(pre.__file__).read_text())
    found = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.If) and isinstance(node.test, ast.Name)
                and node.test.id == "TYPE_CHECKING"):
            for sub in ast.walk(node):
                if isinstance(sub, ast.ImportFrom):
                    found.update(a.name for a in sub.names)
    assert {"LazyTileDataset", "geotiff_to_zarr"} <= found


def test_lazy_stub_does_not_blame_torch_for_other_import_errors(monkeypatch):
    """A failure that is not a missing torch must surface its own error,
    not the "[ml] extra / PyTorch is not installed" hint (a reviewer with
    torch installed was sent down that path by a different missing module)."""
    import importlib
    import sys

    for mod in list(sys.modules):
        if mod.startswith("geoai_datacubes.preprocessing"):
            del sys.modules[mod]
    # None in sys.modules makes `from . import lazy_dataset` raise an
    # ImportError whose .name is the lazy_dataset module, not torch.
    monkeypatch.setitem(sys.modules, "geoai_datacubes.preprocessing.lazy_dataset", None)
    pre = importlib.import_module("geoai_datacubes.preprocessing")
    with pytest.raises(ImportError) as info:
        pre.geotiff_to_zarr
    assert "PyTorch is not installed" not in str(info.value)
    assert "lazy_dataset" in str(info.value)
