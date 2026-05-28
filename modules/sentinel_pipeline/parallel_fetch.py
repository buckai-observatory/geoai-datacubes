# parallel_fetch.py
"""
Parallel Sentinel Data Fetcher
--------------------------------
Fetches multiple Sentinel scenes in parallel (e.g., different ROIs or time ranges)
using ThreadPoolExecutor for faster throughput.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from fetch_data import fetch_sentinel_data
from config import get_config_from_env
import os, time

# === USER CONFIG ===
# Credentials are loaded from environment variables / a local .env file.
# See .env.example at the repo root for setup instructions.

MISSION = "Sentinel-2"
BANDS = ["B04", "B08"]
RESOLUTION = 10
TIME_RANGES = [
    ("2024-06-01", "2024-06-05"),
    ("2024-06-10", "2024-06-15"),
    ("2024-06-20", "2024-06-25")
]
ROIS = [
    [-118.30, 34.00, -118.20, 34.10],
    [-83.00, 40.00, -82.80, 40.20],
    [-122.40, 37.70, -122.30, 37.80]
]

MAX_WORKERS = 3  # concurrent downloads

# === SETUP ===
config = get_config_from_env()
os.makedirs("data_parallel", exist_ok=True)

def download_task(roi, time_range):
    start = time.time()
    data = fetch_sentinel_data(
        config=config,
        mission=MISSION,
        bands=BANDS,
        time_range=time_range,
        roi=roi,
        resolution=RESOLUTION,
        save_folder="data_parallel"
    )
    elapsed = time.time() - start
    return {"roi": roi, "time_range": time_range, "status": "✅", "time": round(elapsed, 2)}

if __name__ == "__main__":
    print(f"🚀 Starting parallel Sentinel-{MISSION[-1]} downloads...")
    futures = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        for roi, time_range in zip(ROIS, TIME_RANGES):
            futures.append(executor.submit(download_task, roi, time_range))

        for f in as_completed(futures):
            result = f.result()
            print(f"✅ Done {result['roi']} ({result['time_range'][0]}–{result['time_range'][1]}) in {result['time']}s")

    print("\n✅ All parallel downloads complete → saved to /data_parallel/")
