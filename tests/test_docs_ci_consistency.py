"""The install docs and the CI workflows must describe the same thing.

Twice during the JOSS review a command in ``docs/install.md`` was posted
to a reviewer without CI having run it (a stale lockfile, then an
environment that could not run the notebooks). These tests make the
three sources of truth check each other:

* every pixi environment named in ``docs/install.md`` exists in
  ``pyproject.toml``;
* the environment the docs recommend for the notebooks is the one the
  ``notebooks`` workflow installs with ``--locked`` and runs the
  notebooks in;
* the ``tests`` environment the docs call "what CI runs" is installed
  with ``--locked`` by ``tests.yml``, which also runs ``pixi lock --check``.

They read the files as text (plus ``tomllib`` for ``pyproject.toml``) so
they need nothing beyond the standard library.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALL_MD = ROOT / "docs" / "install.md"
PYPROJECT = ROOT / "pyproject.toml"
TESTS_YML = ROOT / ".github" / "workflows" / "tests.yml"
NOTEBOOKS_YML = ROOT / ".github" / "workflows" / "notebooks.yml"
RUNNER = ROOT / "smoke-tests" / "run_notebook.py"

NOTEBOOKS_ENV = "notebooks"
FULL_ENV = "full"
NOTEBOOKS_RUN_IN_CI = (
    "notebooks/00_geoai_datacubes_tour.ipynb",
    "notebooks/01_classification.ipynb",
)
# Runs in the `full` environment, only on the weekly schedule and on
# manual dispatch (too slow for a pull-request check).
NOTEBOOK_03 = "notebooks/03_with_opengeos_geoai.ipynb"


def _pixi_environments() -> set[str]:
    with PYPROJECT.open("rb") as fh:
        data = tomllib.load(fh)
    return set(data["tool"]["pixi"]["environments"])


def _code_blocks(md: str) -> list[str]:
    return re.findall(r"```[a-z]*\n(.*?)```", md, flags=re.S)


def _envs_named_in_install_docs() -> set[str]:
    """Every `-e <env>` after a pixi command, in code blocks and prose."""
    text = INSTALL_MD.read_text()
    return set(re.findall(r"pixi (?:install|run|shell)\s+(?:--locked\s+)?-e\s+([a-z]+)", text))


def _setup_pixi_blocks(yml: str) -> list[dict[str, str]]:
    """Each `uses: prefix-dev/setup-pixi` step's `with:` keys, as text."""
    blocks = []
    for m in re.finditer(r"uses: prefix-dev/setup-pixi@[^\n]+\n((?:[ \t]+[^\n]*\n?)+)", yml):
        body = m.group(1)
        kv = {}
        for line in body.splitlines():
            line = line.split("#", 1)[0].strip()
            if ":" in line:
                k, v = line.split(":", 1)
                kv[k.strip()] = v.strip()
        blocks.append(kv)
    return blocks


def test_install_docs_name_only_real_pixi_environments():
    named = _envs_named_in_install_docs()
    assert NOTEBOOKS_ENV in named, "install.md no longer tells users about the notebooks env"
    unknown = named - _pixi_environments()
    assert not unknown, f"docs/install.md names pixi environments that do not exist: {unknown}"


def test_install_docs_give_the_notebook_commands_ci_runs():
    text = INSTALL_MD.read_text()
    for cmd in (f"pixi install -e {NOTEBOOKS_ENV} --locked",
                f"pixi run -e {NOTEBOOKS_ENV} jupyter lab"):
        assert cmd in text, f"docs/install.md must contain the command {cmd!r}"


def test_notebooks_workflow_installs_the_documented_env_locked():
    yml = NOTEBOOKS_YML.read_text()
    blocks = _setup_pixi_blocks(yml)
    assert blocks, "notebooks.yml has no setup-pixi step"
    envs = {b.get("environments") for b in blocks}
    assert envs == {NOTEBOOKS_ENV, FULL_ENV}, \
        f"notebooks.yml installs {envs}, docs recommend {NOTEBOOKS_ENV!r} (00, 01) and {FULL_ENV!r} (03)"
    assert all(b.get("locked") == "true" for b in blocks), "notebooks.yml must install with locked: true"
    assert "macos" in yml, "the notebooks job should run on macOS (the reviewers' platform)"
    assert FULL_ENV in _envs_named_in_install_docs()


def test_notebooks_workflow_executes_the_notebooks_the_docs_promise():
    yml = NOTEBOOKS_YML.read_text()
    assert RUNNER.is_file()
    assert "smoke-tests/run_notebook.py" in yml
    for nb in NOTEBOOKS_RUN_IN_CI:
        assert (ROOT / nb).is_file(), nb
        assert nb in yml, f"{nb} is not executed by notebooks.yml"
    # Each run must be made from the locked environment and must verify
    # the kernel is that environment's Python.
    runs = re.findall(r"pixi run --locked -e notebooks python smoke-tests/run_notebook.py", yml)
    assert len(runs) == len(NOTEBOOKS_RUN_IN_CI)
    assert yml.count("--expect-prefix") == len(NOTEBOOKS_RUN_IN_CI) + 1  # + notebook 03


def test_notebooks_workflow_runs_notebook_03_from_full_env_on_schedule():
    yml = NOTEBOOKS_YML.read_text()
    assert (ROOT / NOTEBOOK_03).is_file()
    assert NOTEBOOK_03 in yml, f"{NOTEBOOK_03} is not executed by notebooks.yml"
    assert re.search(r"pixi run --locked -e full python smoke-tests/run_notebook.py", yml)
    assert "schedule" in yml and "workflow_dispatch" in yml
    # The 03 job must be gated so pull requests stay fast.
    assert "github.event_name == 'schedule' || github.event_name == 'workflow_dispatch'" in yml


def test_tests_workflow_checks_the_lockfile():
    yml = TESTS_YML.read_text()
    blocks = _setup_pixi_blocks(yml)
    assert any(b.get("environments") == "tests" and b.get("locked") == "true" for b in blocks), \
        "tests.yml must install the `tests` env with locked: true"
    assert "pixi lock --check" in yml
    commands = "\n".join(line.split("#", 1)[0] for line in yml.splitlines())
    assert "--frozen" not in commands, "--frozen skips the lockfile check that caught the Oct 2026 drift"
    assert "tests" in _envs_named_in_install_docs()


def test_pixi_tasks_do_not_shadow_documented_executables():
    """`pixi run <task> args` appends args to the task's command, so a task
    named `jupyter` turned the documented `pixi run -e notebooks jupyter lab`
    into `jupyter lab lab`, which fails with "No such file or directory".
    """
    with PYPROJECT.open("rb") as fh:
        tasks = set(tomllib.load(fh)["tool"]["pixi"].get("tasks", {}))
    text = "\n".join(_code_blocks(INSTALL_MD.read_text())) + "\n" + INSTALL_MD.read_text()
    # executables the docs call *with arguments* through `pixi run`
    called = set(re.findall(r"pixi run\s+(?:--locked\s+)?(?:-e\s+[a-z]+\s+)?([a-z][a-z0-9_-]*)\s+[a-z-]", text))
    clash = tasks & called
    assert not clash, f"pixi task(s) {clash} shadow executables that docs/install.md invokes with arguments"
    assert "jupyter" not in tasks


def test_shipped_notebooks_print_the_kernel_path():
    """run_notebook.py relies on the first code cell printing it."""
    import json
    for nb in NOTEBOOKS_RUN_IN_CI + (NOTEBOOK_03,):
        cells = json.loads((ROOT / nb).read_text())["cells"]
        first = next(c for c in cells if c["cell_type"] == "code")
        assert "kernel python:" in "".join(first["source"]), nb
