"""A threadpool_limits block must not leave PyTorch convolutions hanging.

With threadpoolctl 3.6.0 in the locked pixi environment (macOS arm64), a
`threadpool_limits(limits=1)` block followed by a single-threaded PyTorch
forward pass never returned, which stalled notebook 01. The check runs in a
subprocess with a timeout so a regression fails instead of hanging CI.
"""
import subprocess
import sys
import textwrap

import pytest

pytest.importorskip("torch")
pytest.importorskip("threadpoolctl")

SCRIPT = textwrap.dedent("""
    import numpy as np, torch
    from threadpoolctl import threadpool_limits
    from sklearn.linear_model import LogisticRegression

    torch.set_num_threads(1)
    conv = torch.nn.Sequential(
        torch.nn.Conv2d(6, 16, 3, padding=1), torch.nn.ReLU(),
        torch.nn.ConvTranspose2d(16, 8, 2, stride=2)).eval()
    x = torch.rand(4, 6, 128, 128)

    X = np.random.rand(2000, 8); y = (X[:, 0] > 0.5).astype(int)
    with threadpool_limits(limits=1):
        LogisticRegression(max_iter=100).fit(X, y)

    with torch.no_grad():
        conv(x)
    print("ok")
""")


def test_single_thread_conv_after_threadpool_limits_returns():
    pytest.importorskip("sklearn")
    try:
        out = subprocess.run([sys.executable, "-c", SCRIPT], capture_output=True,
                             text=True, timeout=120)
    except subprocess.TimeoutExpired:
        pytest.fail("PyTorch forward pass hung after threadpool_limits(limits=1)")
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "ok"
