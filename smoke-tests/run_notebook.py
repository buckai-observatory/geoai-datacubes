"""Execute one shipped notebook top to bottom and fail on the first cell error.

This is what the `notebooks` CI workflow runs, from the locked pixi
`notebooks` environment on a macOS (Apple silicon) runner, for notebooks
00 and 01. It is also usable locally:

    pixi run -e notebooks python smoke-tests/run_notebook.py \
        notebooks/00_geoai_datacubes_tour.ipynb \
        --expect-prefix "$PWD/.pixi/envs/notebooks"

What it does:

* starts the `python3` kernel with the notebook's own folder as working
  directory (the notebooks locate the repo root from `Path.cwd()`);
* refuses to run if that kernelspec points at a Python outside
  ``--expect-prefix`` (the "installed but import fails" trap: a Jupyter
  from another environment picking up its own kernel);
* logs every code cell with its first line and wall time, so a hang or
  a slow fetch is visible in the CI log while it happens;
* on a cell error prints that cell's traceback and exits 1;
* after the run, checks that the first code cell printed a
  ``kernel python:`` line inside ``--expect-prefix``;
* writes the executed notebook (outputs included) to ``--out`` so CI can
  upload it as an artifact.

Only `nbformat`, `nbclient` and `jupyter_client` are needed; all three
come with JupyterLab.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import nbformat
from jupyter_client.kernelspec import KernelSpecManager, NoSuchKernel
from nbclient import NotebookClient
from nbclient.exceptions import CellExecutionError


def _first_line(cell) -> str:
    for line in cell.source.splitlines():
        s = line.strip()
        if s and not s.startswith("%%"):
            return s[:72]
    return ""


def _kernel_python(kernel_name: str) -> str:
    """Absolute path of the interpreter the kernelspec will start."""
    try:
        spec = KernelSpecManager().get_kernel_spec(kernel_name)
    except NoSuchKernel:
        sys.exit(f"no kernelspec named {kernel_name!r}; is ipykernel installed "
                 f"in {sys.prefix}?")
    exe = spec.argv[0]
    if exe in ("python", "python3"):
        # ipykernel writes a relative 'python' into the spec when the
        # environment is relocatable; resolve it the way Jupyter does.
        exe = sys.executable
    return os.path.realpath(exe)


def _within(path: str, prefix: str) -> bool:
    return os.path.realpath(path).startswith(os.path.realpath(prefix) + os.sep)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("notebook", type=Path)
    ap.add_argument("--out", type=Path, default=None,
                    help="where to write the executed notebook "
                         "(default: notebooks/_outputs/executed/<name>.ipynb)")
    ap.add_argument("--timeout", type=int, default=1800,
                    help="per-cell timeout in seconds (default 1800)")
    ap.add_argument("--kernel", default="python3")
    ap.add_argument("--expect-prefix", default=None,
                    help="directory the kernel's Python must live under "
                         "(e.g. the pixi environment); checked before and "
                         "after the run")
    args = ap.parse_args(argv)

    nb_path = args.notebook.resolve()
    if not nb_path.is_file():
        sys.exit(f"notebook not found: {nb_path}")
    out = args.out or (nb_path.parent / "_outputs" / "executed" / nb_path.name)
    out.parent.mkdir(parents=True, exist_ok=True)

    kernel_exe = _kernel_python(args.kernel)
    print(f"notebook       : {nb_path}")
    print(f"kernel         : {args.kernel} -> {kernel_exe}")
    print(f"this python    : {sys.executable}")
    if args.expect_prefix and not _within(kernel_exe, args.expect_prefix):
        print(f"ERROR: kernel Python is not under {args.expect_prefix}; "
              f"a Jupyter from another environment would run this notebook "
              f"with the wrong packages.")
        print("Run `jupyter kernelspec list`: a kernelspec named "
              f"{args.kernel!r} in a user directory (e.g. ~/Library/Jupyter "
              "or ~/.local/share/jupyter) shadows the environment's own. "
              "Remove it, or point JUPYTER_DATA_DIR at an empty folder.")
        return 2

    nb = nbformat.read(nb_path, as_version=4)
    for cell in nb.cells:
        if cell.cell_type == "code":
            cell.outputs = []
            cell.execution_count = None

    timing = {}

    def on_start(cell, cell_index, **_):
        timing[cell_index] = time.time()
        print(f"[{cell_index:3d}] START {_first_line(cell)}", flush=True)

    def on_done(cell, cell_index, execute_reply=None, **_):
        dt = time.time() - timing.get(cell_index, time.time())
        print(f"[{cell_index:3d}] DONE  {dt:7.1f}s", flush=True)

    client = NotebookClient(
        nb,
        timeout=args.timeout,
        kernel_name=args.kernel,
        resources={"metadata": {"path": str(nb_path.parent)}},
        allow_errors=False,
    )
    client.on_cell_start = on_start
    client.on_cell_executed = on_done

    t0 = time.time()
    status = 0
    try:
        client.execute()
    except CellExecutionError as e:
        print(f"\nCELL ERROR after {time.time() - t0:.0f}s:\n{e}", flush=True)
        status = 1
    except Exception as e:  # kernel died, timeout, ...
        print(f"\nEXECUTION FAILED after {time.time() - t0:.0f}s: "
              f"{type(e).__name__}: {str(e)[:2000]}", flush=True)
        status = 1
    finally:
        nbformat.write(nb, out)
        print(f"executed notebook written to {out}")

    # The first code cell of each shipped notebook prints the kernel's
    # Python path. Check it against the expected environment.
    if status == 0 and args.expect_prefix:
        printed = None
        for cell in nb.cells:
            if cell.cell_type != "code":
                continue
            for o in cell.get("outputs", []):
                for line in o.get("text", "").splitlines():
                    if line.startswith("kernel python:"):
                        printed = line.split(":", 1)[1].strip()
            break
        if printed is None:
            print("ERROR: the first code cell did not print a "
                  "'kernel python:' line")
            status = 1
        elif not _within(printed, args.expect_prefix):
            print(f"ERROR: notebook ran under {printed}, not under "
                  f"{args.expect_prefix}")
            status = 1
        else:
            print(f"kernel check   : {printed} (ok)")

    print(f"total          : {time.time() - t0:.0f}s, "
          f"{'OK' if status == 0 else 'FAILED'}")
    return status


if __name__ == "__main__":
    sys.exit(main())
