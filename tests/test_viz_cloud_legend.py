"""plot_cloud_pair adds an SCL class legend that marks the masked classes."""

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from geoai_datacubes.viz import decode_scl, plot_cloud_pair  # noqa: E402


def test_scl_legend_lists_present_classes_and_marks_masked(monkeypatch):
    captured = {}
    monkeypatch.setattr(plt, "show",
                        lambda *a, **k: captured.setdefault("fig", plt.gcf()))
    scl = np.array([[4, 4, 8], [9, 5, 4]], dtype="float32")
    arr = np.stack([np.zeros_like(scl), scl])
    plot_cloud_pair("S2", arr, ["B04", "SCL"], "B04", "SCL", decode_scl)

    legend = captured["fig"].axes[1].get_legend()
    labels = [t.get_text() for t in legend.get_texts()]
    assert labels == ["4: vegetation", "5: bare soil",
                      "8: cloud (medium prob.) (masked)",
                      "9: cloud (high prob.) (masked)"]
    plt.close("all")


def test_no_legend_without_class_names(monkeypatch):
    captured = {}
    monkeypatch.setattr(plt, "show",
                        lambda *a, **k: captured.setdefault("fig", plt.gcf()))
    qa = np.array([[0, 2], [8, 10]], dtype="float32")
    arr = np.stack([np.zeros_like(qa), qa])
    plot_cloud_pair("L", arr, ["B04", "BQA"], "B04", "BQA", lambda q: q > 0)
    assert captured["fig"].axes[1].get_legend() is None
    plt.close("all")
