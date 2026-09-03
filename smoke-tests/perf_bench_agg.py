"""Aggregate one-or-more ``perf_bench_*.jsonl`` logs into a single markdown
table with min / median / max / n across repeats.

Groups rows by (machine-label, config-label). ``machine-label`` is the
prefix of the log file's ``label`` (everything before the last ``-runN``
suffix if present, else the full label) so that

    perf_bench_laptop-cellular_20260903T200131Z.jsonl
    perf_bench_laptop-cellular-run2_20260903T202400Z.jsonl
    perf_bench_laptop-cellular-run3_20260903T204500Z.jsonl

collapse into one ``laptop-cellular`` column, and

    perf_bench_unity-cluster_20260903T203200Z.jsonl

into a separate ``unity-cluster`` column.

Usage:
    python smoke-tests/perf_bench_agg.py [--out DIR] [--min-n N]

    --out       glob dir for jsonl logs (default: smoke-tests/perf_logs)
    --min-n     drop rows with fewer than N observations across all logs
                (default: 1). Useful once we have enough repeats to
                filter out one-offs.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional


_RUN_SUFFIX_RE = re.compile(r"-run\d+$")


def _machine_key(header_label: str) -> str:
    """Collapse per-run suffixes so repeat runs group together."""
    return _RUN_SUFFIX_RE.sub("", header_label)


def _load(paths: List[Path]) -> Dict[str, Dict[str, List[dict]]]:
    """{machine_key: {config_label: [row_dict, ...]}}"""
    out: Dict[str, Dict[str, List[dict]]] = defaultdict(lambda: defaultdict(list))
    for p in paths:
        header: Optional[dict] = None
        try:
            with p.open() as fh:
                for line in fh:
                    d = json.loads(line)
                    if d.get("kind") == "header":
                        header = d
                    elif d.get("kind") == "row" and header:
                        if not d.get("ok"):
                            continue  # skip failures and cred-skips
                        key = _machine_key(header["label"])
                        out[key][d["label"]].append(d)
        except (OSError, json.JSONDecodeError) as e:
            print(f"  ! skipped {p.name}: {e}")
    return out


def _stat(vals: List[float]) -> Dict[str, float]:
    return {
        "n":     len(vals),
        "min":   round(min(vals), 2),
        "med":   round(statistics.median(vals), 2),
        "max":   round(max(vals), 2),
    }


def render(all_rows: Dict[str, Dict[str, List[dict]]]) -> str:
    parts: List[str] = []
    for machine in sorted(all_rows):
        parts.append(f"\n### Machine: `{machine}`\n")
        parts.append(
            "| Row | Mission | Provider | AOI | Bands | Res (m) | "
            "n | Wall min-med-max (s) | Out (MB) | Out (Mpx) | Mpx/s med |"
        )
        parts.append("|---|---|---|---|---|---|---:|---|---:|---:|---:|")
        for label in sorted(all_rows[machine]):
            rows = all_rows[machine][label]
            first = rows[0]
            walls = [r["wall_s"] for r in rows if r.get("wall_s") is not None]
            mbs   = [r["out_tiff_MB"] for r in rows if r.get("out_tiff_MB") is not None]
            pxs   = [r["out_pixels_M"] for r in rows if r.get("out_pixels_M") is not None]
            rate  = [r["px_per_s_M"] for r in rows if r.get("px_per_s_M") is not None]
            w = _stat(walls) if walls else {"n": 0, "min": "—", "med": "—", "max": "—"}
            bands = ",".join(first["bands"]) if first.get("bands") else "default"
            parts.append(
                f"| {label} | {first['mission']} | `{first['provider']}` | "
                f"`{first['aoi_key']}` | {bands} | {first['resolution']} | "
                f"{w['n']} | {w['min']} – {w['med']} – {w['max']} | "
                f"{round(statistics.median(mbs), 1) if mbs else '—'} | "
                f"{round(statistics.median(pxs), 2) if pxs else '—'} | "
                f"{round(statistics.median(rate), 2) if rate else '—'} |"
            )
    parts.append(
        "\n_Wall column is min–median–max across `n` successful runs. "
        "Out (MB), Out (Mpx), Mpx/s show the median. Rows with no "
        "successful observations are omitted. See "
        "`smoke-tests/perf_bench.py` for the harness and "
        "`docs/architecture.qmd` for the pipeline shape being measured._"
    )
    return "\n".join(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="smoke-tests/perf_logs",
                    help="dir of *.jsonl logs to aggregate")
    ap.add_argument("--min-n", type=int, default=1,
                    help="drop rows with fewer than this many successful runs")
    ap.add_argument("--machine", action="append", default=None,
                    help="only include this machine-label (repeatable). "
                         "The machine key is the log's header 'label' with "
                         "any '-runN' suffix stripped, so passing "
                         "'--machine laptop-cellular' matches labels like "
                         "'laptop-cellular', 'laptop-cellular-run2', etc.")
    args = ap.parse_args()

    log_dir = Path(args.out)
    paths = sorted(log_dir.glob("perf_bench_*.jsonl"))
    if not paths:
        print(f"no perf_bench_*.jsonl in {log_dir}")
        return
    print(f"==> aggregating {len(paths)} log(s)")
    all_rows = _load(paths)

    if args.machine:
        wanted = set(args.machine)
        all_rows = {m: v for m, v in all_rows.items() if m in wanted}
        missing = wanted - set(all_rows)
        if missing:
            print(f"==> warning: requested machine(s) not found: {sorted(missing)}")

    if args.min_n > 1:
        for m in list(all_rows):
            all_rows[m] = {k: v for k, v in all_rows[m].items() if len(v) >= args.min_n}
            if not all_rows[m]:
                del all_rows[m]

    total = sum(len(cfg) for m in all_rows.values() for cfg in m.values())
    print(f"==> {sum(len(m) for m in all_rows.values())} config(s), "
          f"{total} total observation(s), across {len(all_rows)} machine(s)")
    print()
    print(render(all_rows))


if __name__ == "__main__":
    main()
