"""Smoke test: package imports cleanly and exposes __version__."""
import re

import geoai_datacubes


def test_version_attribute_is_set():
    assert hasattr(geoai_datacubes, "__version__")
    assert isinstance(geoai_datacubes.__version__, str)
    assert geoai_datacubes.__version__ != ""


def test_version_looks_like_pep440():
    # PEP 440 / setuptools_scm format. Accepts e.g.
    #   "0.1.0", "0.1.0.dev3+gabcdef", "0.2.0rc1", "0.1.0.post1"
    pattern = re.compile(
        r"^\d+(\.\d+){0,3}"        # 0.1.0 / 1 / 1.2 / 1.2.3.4
        r"(\.(dev|post|a|b|rc)\d+)?"
        r"(\+[a-zA-Z0-9._-]+)?$"
    )
    assert pattern.match(geoai_datacubes.__version__), \
        f"unexpected version string: {geoai_datacubes.__version__!r}"
