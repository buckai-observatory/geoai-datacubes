# AGENTS.md — geoai-datacubes

Instructions for AI coding assistants (Claude Code, Gemini CLI, OpenAI
Codex CLI, Cursor, Windsurf, ...) working in the `geoai-datacubes`
repository. If your tool uses a different filename (`CLAUDE.md`,
`GEMINI.md`, `.cursor/rules/*.md`), symlink or copy this file so it
loads automatically.

Nothing in `agents/` uses tool-specific features (no MCP schemas,
no slash commands, no Skill/Artifact hooks). Every skill is plain
English + shell/Python blocks + filesystem references.

---

## What this repo is

`geoai-datacubes` is a BuckAI Observatory pipeline that turns raw
satellite scenes into **AI-ready, multi-mission, fused data cubes**.
39 missions (optical, SAR, LIDAR/altimetry, DEM/bathymetry, LULC,
biomass, thermal, hydrology, cryosphere, atmosphere, soil) behind one
`fetch_sentinel_data(mission, bands, time_range, roi, resolution=...)`
call and one `fuse_response_tiffs(...)` fusion step, dispatched across
seven interchangeable providers (four STAC + `direct_http` +
`earth_engine` + `earthdata`).

Reference material you should consult before making up anything:

- `README.md` — collapsible mission tables grouped by modality.
- `docs/data_layers.md` — authoritative per-mission band / resolution /
  norm reference. **Never invent bands**; always cross-check here.
- `docs/providers.md` + `docs/providers/*.md` — provider capabilities,
  routing, auth walkthroughs.
- `docs/install.md` — install matrix + extras.
- `notebooks/00_geoai_datacubes_tour.ipynb`,
  `notebooks/01_classification.ipynb`,
  `notebooks/04_earth_engine_dynamic_world.ipynb`,
  `notebooks/05_nisar_arctic_datacube.ipynb` — style and structure to
  match when you scaffold a new notebook.

## What you can do for the user

You are the **primary interface** for the ~80% case: the scientist
wants a fused datacube over their AOI and time window, optionally
followed by a baseline ML/DL model on it. Everything short of
research-novel modelling (custom loss functions, PINN training,
foundation-model fine-tuning) should be doable end-to-end by
conversing with you — no requirement that the user knows the
Python API.

You may:

- Pick missions and bands, resolve AOIs, run fetches, fuse cubes,
  visualise them, tile them, and train baseline classifiers /
  regressors / segmenters end-to-end.
- Scaffold a Jupyter notebook that replays the whole workflow.
- Walk the user through provider auth (Earthdata Login, Earth Engine,
  Sentinel Hub, Planet).
- Add a new mission profile behind their supervision (see
  `docs/adding_a_mission.md`).

You must not:

- Commit or push without explicit user approval.
- Add `Co-Authored-By: Claude` (or any AI) trailers to commits.
- Paste credentials into files, chats, or notebook outputs.
- Silently switch to a paid provider (Planet, Sentinel Hub PU-heavy
  workloads) — always confirm cost implications first.
- Invent bands, mission keys, or API signatures. Verify against
  `docs/data_layers.md` and `MISSION_PROFILES` in
  `geoai_datacubes/fetch/missions.py`.

## First conversation — the script

On your very first turn in a fresh session, do this before anything
else. Do not skip steps because the user's request seems obvious;
the sniff sets defaults every downstream skill depends on.

**Step 1 — Environment sniff (silent, no prompts to the user).**

Run exactly one command:

```bash
scripts/geoai-python -m geoai_datacubes sniff
```

Don't reconstruct this as inline bash/python one-liners, even though
it would be easy to. The `sniff` command does the whole sniff (Python
version, interpreter path, `geoai_datacubes` + extras, Colab
detection) *and* the readiness check (repo identity, conda env
match) in one process, printed as plain lines. Two reasons this
needs to stay one script invocation rather than several inline
commands:

1. `conda activate` silently no-ops in a non-interactive shell more
   often than not, and a bare `python` afterwards then quietly runs
   against base/system Python, missing half of what this repo needs
   — that mismatch is the single most common source of
   `ModuleNotFoundError`s and version-clash errors in this repo, not
   real package incompatibilities. `scripts/geoai-python` (the
   wrapper this is invoked through) resolves the right interpreter by
   absolute path instead.
2. **Every command sharing one exact shape is what lets a permission
   allowlist actually work.** `.claude/settings.json` allowlists
   `Bash(scripts/geoai-python *)` — any invocation of the wrapper,
   including this one, matches that single pattern and needs no
   approval. Reconstructing the same checks as inline `if`/`case`
   bash (which was tried once already) produces a command that starts
   with `if`, not `scripts/geoai-python`, doesn't match the
   allowlist, and prompts every time even though it's logically doing
   the same safe, read-only thing. If a check needs to be added to
   the sniff, add it to `cmd_sniff` in `geoai_datacubes/cli.py` and
   keep calling it the same way — don't grow a second, differently-
   shaped command next to it.

Only report "ready to go" if the `repo:`, `package:` and
`conda env:` lines all say `OK`. (`package:` checks that Python is
using this checkout's code and not another installed copy.) If either says `MISMATCH`, say so
plainly and fix it (wrong directory → ask the user; wrong env →
`skills/00_bootstrap.md`) before doing anything else — don't print a
reassuring summary over a check that actually failed. If
`geoai_datacubes` imports but a specific extra you'll need shows
`MISS`, go to `skills/00_bootstrap.md` and ask the user whether to
install it (never install silently — extras vary from small to
multi-GB).

Close Step 1 with a short banner so the user has immediate, verified
confirmation instead of having to parse the raw sniff output —
something like:

```
Ready: repo=geoai-datacubes, env=geoai-cubes, geoai_datacubes v0.1.1.dev70.
```

If this looks like it's heading toward a live demo (user mentions
"demo", asks to fetch imagery over a place with no other context, or
says so directly), also read `skills/demo.md` now and let its own
readiness note add a few example prompts on top of this banner —
don't wait for the user to hit a wall first.

**Step 2 — Confirm the goal in one sentence.**

Ask the user to complete: *"I want to build a datacube [for what
purpose] over [AOI] for [time window]."* If they can't answer any
one of the three, that's fine — the cube-build skill walks them
through each defaulting.

**Step 3 — Offer the menu.**

Point them at the skill that matches their goal:

- "Just fetch and fuse a cube" → `skills/20_build_cube.md`
- "I don't know which missions I want" → `skills/10_capabilities.md`
- "Auth is broken / never set up" → `skills/30_auth.md`
- "Save what we built as a notebook" → `skills/40_notebook_scaffold.md`
- "Now train a baseline model on the cube" → `skills/50_ml_scaffold.md`
- Live/interactive demo, user gives underspecified requests → `skills/demo.md`

Then go do it. Do not lecture the user through the skill's text
verbatim — read the skill, act on it.

## The `geoai-datacubes` command

Common requests have one tested command each. Use them instead of
writing a new script; they print per-step timing and write a QGIS
project (`.qgs`) that opens every sensible view of the result.

```bash
scripts/geoai-python -m geoai_datacubes cube "<place>" [--missions ...] [--radius-km 2] [--tiles]
scripts/geoai-python -m geoai_datacubes embed-change "<place>" [--from 2017] [--to <year>]
scripts/geoai-python -m geoai_datacubes embed-similar "<place or AlphaEarth tiff>" --at "<reference place>"
scripts/geoai-python -m geoai_datacubes style <cube.tiff>      # QGIS styles for any GeoTIFF
scripts/geoai-python -m geoai_datacubes quality <cube.tiff>
scripts/geoai-python -m geoai_datacubes tiles <cube.tiff>
scripts/geoai-python -m geoai_datacubes geocode "<place>"
scripts/qgis <file.qgs or file.tiff ...>                       # open in QGIS
```

`<place>` can be a name, `"lat, lon"`, or an alias from
`.geoai-places.json` in the repo root. After `pip install
geoai-datacubes[demo]` the same command is available as
`geoai-datacubes <command>`; in this repo, go through
`scripts/geoai-python -m geoai_datacubes` so the allow-list matches
and this checkout's code is used. Run `... <command> --help` for all
options.

## Menu of skill files

Every skill file under `agents/skills/` opens with a one-para "when
to invoke this" header and ends with a "handoff" section pointing to
the next skill. They are numbered in the order a typical session
touches them, but you may jump straight to any of them.

| Skill | Purpose | Load when |
|---|---|---|
| `skills/00_bootstrap.md` | Env sniff → install → smoke test | Session start, or after `ImportError` |
| `skills/10_capabilities.md` | Enumerate 39 missions; answer "which mission for X?" | User asks what's available; you need to check a band before promising it |
| `skills/15_mission_reference.md` | Quick-reference tables for all missions (res, bands, best-for, decision tree) | User asks "what's available?" and you want instant lookup instead of reading docs |
| `skills/20_build_cube.md` | End-to-end fetch + fuse workflow | User wants a cube (the common case) |
| `skills/30_auth.md` | Per-provider credential setup | 401 / 403 / `EulaNotAccepted` / EE `Initialize` failure |
| `skills/40_notebook_scaffold.md` | Write a Jupyter notebook that replays the workflow | User wants a permanent artefact |
| `skills/50_ml_scaffold.md` | Standard ML/DL patterns on a cube | User wants a baseline model |
| `skills/demo.md` | Defaults for underspecified live-demo requests (AOI radius, auto-open in QGIS, hillshade-vs-RGB) | Live/interactive demo session |

## Escape hatches — when to STOP and hand back

Stop, summarise what's been built, and hand control to the user
before proceeding when any of these come up:

- **Novel methodology.** User mentions a custom loss function, PINN,
  novel architecture, or foundation-model fine-tuning they want
  control over. Fuse the cube, write the notebook scaffold, then
  step out with: *"Cube and DataLoader ready at `<path>`. The
  training loop is yours — I'd need paper-specific guidance to
  write it."*
- **Cost-sensitive downloads.** Any single fetch >~5 GB, any
  Sentinel Hub run projected past the free-tier PUs, any Planet
  order (commercial). Print the estimate, ask before proceeding.
- **Credential setup that needs a browser.** EE first-time
  `ee.Authenticate()`, Earthdata Login registration, DAAC-app
  approval, Planet API key generation. Read the relevant section of
  `skills/30_auth.md`, print the exact URLs + steps, wait for the
  user to complete them and paste back a confirmation.
- **Destructive git.** `git push --force`, `git reset --hard`, any
  history rewrite. Always confirm.
- **Committing.** Never commit without explicit approval. `git add`
  is fine as a preview; `git commit` is not.
- **Uncertainty.** If you're guessing whether a band exists, a
  mission covers an AOI, or an API signature matches — stop and
  check `docs/data_layers.md`, `MISSION_PROFILES`, or ask the user.
  A confidently hallucinated `import` is worse than "I need to
  check that."

## Style rules for anything you write

- No decorative emojis in code or docs. Functional log indicators
  (`OK`, `WARN`, `MISS`, or the existing `✅ / ❌ / ⚠️` in log
  strings) are fine.
- Comments explain **why**, not what.
- All in-figure text bold; use line styles + colours (colour-blind
  reader); no figure titles (caption instead); dpi=300 or vector.
  Exact rcParams block is inlined in `skills/40_notebook_scaffold.md`
  (paste it into your notebook, do not reference a user-local file).
- Absolute file paths in reports back to the user, not relative.

## Handoff

If the user has said what they want, jump to
`skills/20_build_cube.md` and start there. If they haven't, or if
the environment isn't ready, go through `skills/00_bootstrap.md`
first.
