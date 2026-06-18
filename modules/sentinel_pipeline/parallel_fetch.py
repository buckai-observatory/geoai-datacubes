# parallel_fetch.py
"""
Parallel Sentinel Data Fetcher
--------------------------------
Fetches multiple Sentinel scenes in parallel (e.g., different ROIs or time ranges)
using ThreadPoolExecutor for faster throughput.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from fetch_data import fetch_sentinel_data
from aoi import resolve_aoi
import os, time

# === USER CONFIG ===
# Provider:  "auto"               (default; ES for S2, PC for S1 RTC + Landsat -- all no-creds)
#            "earthsearch"        (Element 84 STAC; works for Sentinel-2 only)
#            "planetary_computer" (Microsoft Planetary Computer; works for all 4 missions)
#            "sentinelhub"        (advanced; requires .env credentials)
PROVIDER = "auto"

MISSION = "Sentinel-2"   # "Sentinel-2", "Sentinel-2-L1C", "Sentinel-1", or "Landsat"
BANDS = ["B04", "B08"]   # for Landsat use ["B04", "B05"] (Red, NIR)
RESOLUTION = 10
TIME_RANGES = [
    ("2024-06-01", "2024-06-05"),
    ("2024-06-10", "2024-06-15"),
    ("2024-06-20", "2024-06-25"),
]
# AOIs to fetch in parallel. Each entry uses the same flexible spec as main.py
# (see aoi.py): a {"bbox": ...}, {"shapefile": ...}, {"center": ..., "side_miles": ...},
# or {"tile_around": ...} dict. Example below: three 5-mile squares in/around Columbus.
AOIS = [
    {"center": (40.0067, -83.0305), "side_miles": 5},   # OSU main campus
    {"center": (39.9612, -82.9988), "side_miles": 5},   # downtown Columbus
    {"center": (40.0992, -83.1141), "side_miles": 5},   # Dublin / Olentangy floodplain
]
ROIS = [resolve_aoi(a) for a in AOIS]

MAX_WORKERS = 3  # concurrent downloads

os.makedirs("data_parallel", exist_ok=True)

def download_task(roi, time_range):
    start = time.time()
    data, _ = fetch_sentinel_data(
        mission=MISSION,
        bands=BANDS,
        time_range=time_range,
        roi=roi,
        resolution=RESOLUTION,
        save_folder="data_parallel",
        provider=PROVIDER,
    )
    elapsed = time.time() - start
    return {"roi": roi, "time_range": time_range, "status": "✅", "time": round(elapsed, 2)}

if __name__ == "__main__":
    print(f"🚀 Starting parallel {MISSION} downloads...")
    futures = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        for roi, time_range in zip(ROIS, TIME_RANGES):
            futures.append(executor.submit(download_task, roi, time_range))

        for f in as_completed(futures):
            result = f.result()
            print(f"✅ Done {result['roi']} ({result['time_range'][0]}–{result['time_range'][1]}) in {result['time']}s")

    print("\n✅ All parallel downloads complete → saved to /data_parallel/")
