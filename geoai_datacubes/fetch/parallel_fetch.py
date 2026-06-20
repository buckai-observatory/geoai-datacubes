"""Concurrent fetch of multiple AOIs / missions / time windows.

Wraps :func:`fetch_sentinel_data` with a ``concurrent.futures.ThreadPoolExecutor``
so independent fetches run in parallel. The library function
:func:`fetch_many_in_parallel` is what the pedagogical notebooks import
(it returns a list of result dicts so the caller can render their own
progress / metrics); the ``__main__`` block at the bottom is a worked
CLI example that re-uses the same helper.

Threading is the right tool here -- the bottleneck is network I/O
(STAC search, COG byte-range reads), not CPU -- and works equally
well on a laptop and on Colab.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Sequence
import os
import time

from .fetch_data import fetch_sentinel_data
from .aoi import resolve_aoi


def fetch_many_in_parallel(
    jobs: Sequence[Dict[str, Any]],
    *,
    labels: Optional[Sequence[str]] = None,
    max_workers: int = 3,
    progress: bool = True,
) -> List[Dict[str, Any]]:
    """Run multiple ``fetch_sentinel_data`` calls in parallel and return
    one result dict per job.

    Each item in ``jobs`` is a kwargs dict for ``fetch_sentinel_data``
    (mission, bands, time_range, roi, resolution, save_folder, ...).
    Each item in the optional ``labels`` list is a short human-readable
    name for the corresponding job, used in the progress printout and
    echoed back in the result dicts. If omitted, jobs are labelled
    "job 0", "job 1", ...

    Parameters
    ----------
    jobs
        List of ``fetch_sentinel_data`` kwargs dicts. Each one is run
        independently in its own thread; the underlying STAC + COG
        reads do their own I/O so they parallelise cleanly.
    labels
        Optional human-readable labels (one per job). Useful when the
        jobs differ by city / time-range and you want the progress
        log to identify them by name.
    max_workers
        Number of concurrent fetches. 3 is a safe default for
        Planetary Computer (higher counts can trip rate limits).
        Threading -- not multiprocessing -- because the work is
        network-bound; ``GIL``-bound CPU work would not benefit.
    progress
        If True, print a one-line ``label  status  elapsed`` row per
        job as each completes.

    Returns
    -------
    list of dict
        One per input job, in the same order. Each dict has:

        * ``label`` -- the label for this job
        * ``status`` -- ``"ok"`` or ``"error"``
        * ``elapsed`` -- seconds the fetch took
        * ``bands`` -- the band list returned by ``fetch_sentinel_data``
          (None on error)
        * ``error`` -- the exception string on error (None on success)

        The downloaded GeoTIFFs themselves land in the
        ``save_folder`` directory each job specified.
    """
    n = len(jobs)
    if labels is None:
        labels = [f"job {i}" for i in range(n)]
    if len(labels) != n:
        raise ValueError(
            f"len(labels)={len(labels)} does not match len(jobs)={n}"
        )

    results: List[Optional[Dict[str, Any]]] = [None] * n

    def _run_one(i: int) -> None:
        t0 = time.time()
        try:
            _, bands = fetch_sentinel_data(**jobs[i])
            results[i] = {
                "label":   labels[i],
                "status":  "ok",
                "elapsed": time.time() - t0,
                "bands":   bands,
                "error":   None,
            }
        except Exception as exc:
            results[i] = {
                "label":   labels[i],
                "status":  "error",
                "elapsed": time.time() - t0,
                "bands":   None,
                "error":   f"{type(exc).__name__}: {exc}",
            }

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(_run_one, i): i for i in range(n)}
        for fut in as_completed(futures):
            i = futures[fut]
            fut.result()    # propagate any executor-internal failure
            if progress:
                r = results[i]
                tag = "OK " if r["status"] == "ok" else "ERR"
                print(f"  [{tag}] {r['label']:20s}  {r['elapsed']:5.1f} s")

    return results   # type: ignore[return-value]


# ============================================================
# Example CLI: parallel Sentinel-2 fetches over three Columbus AOIs.
# Invoke from the repository root with:
#     python -m geoai_datacubes.fetch.parallel_fetch
# ============================================================
if __name__ == "__main__":
    PROVIDER    = "auto"
    MISSION     = "Sentinel-2"
    BANDS       = ["B04", "B08"]
    RESOLUTION  = 10
    TIME_RANGES = [
        ("2024-06-01", "2024-06-05"),
        ("2024-06-10", "2024-06-15"),
        ("2024-06-20", "2024-06-25"),
    ]
    AOIS = [
        {"center": (40.0067, -83.0305), "side_miles": 5},   # OSU campus
        {"center": (39.9612, -82.9988), "side_miles": 5},   # downtown Columbus
        {"center": (40.0992, -83.1141), "side_miles": 5},   # Dublin
    ]

    os.makedirs("data_parallel", exist_ok=True)

    jobs = [
        {
            "mission":     MISSION,
            "bands":       BANDS,
            "time_range":  tr,
            "roi":         resolve_aoi(aoi),
            "resolution":  RESOLUTION,
            "save_folder": "data_parallel",
            "provider":    PROVIDER,
        }
        for aoi, tr in zip(AOIS, TIME_RANGES)
    ]
    labels = [
        f"aoi{i+1} {tr[0]}..{tr[1]}"
        for i, tr in enumerate(TIME_RANGES)
    ]

    print(f"Starting {len(jobs)} parallel {MISSION} downloads ...")
    results = fetch_many_in_parallel(jobs, labels=labels, max_workers=3)
    n_ok = sum(1 for r in results if r["status"] == "ok")
    print(f"\n{n_ok}/{len(results)} downloads succeeded. "
          f"Output -> data_parallel/")
