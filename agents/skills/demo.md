# Skill — Demo defaults

**When to invoke.** Live/interactive demo sessions where the user
gives an underspecified request that matches one of the patterns
below — *"get me the latest Sentinel-2 image over X"*, *"open the
results"*, *"show me the DEM"*. Stopping to ask clarifying questions
kills a demo's flow; this skill is the set of defaults to apply
instead of asking, so those requests just work.

Goal: keep demo requests moving. This skill does not replace
`skills/20_build_cube.md` — it fixes the defaults (AOI radius, cloud
policy, visualisation) so that skill's steps don't need a
back-and-forth first.

---

## Reading this file — say so, don't just act on it

`AGENTS.md`'s Step 1 already ran the repo/env readiness check before
this file gets read. Once this file is loaded too, say so explicitly
and offer a few concrete example prompts, rather than silently
absorbing the defaults below and waiting for the user to ask
something. Something like:

```
Demo defaults loaded (agents/skills/demo.md) — AOI radius, auto-QGIS,
hillshade/RGB, tiling, quality reports, and classification styling are
all pre-set, no need to specify them each time. Ready for things like:

  "get me the latest Sentinel-2 image over Lipari"
  "add LULC and show the classification layer" (over Pokhara/Annapurna)
  "show how this area changed since 2017" (AlphaEarth change map)
  "find places around here that look like Ohio Stadium" (AlphaEarth)
  "get me a Sentinel-2 + DEM cube over Stromboli, then a quality report"
  "turn this into training tiles" (128px, 25% overlap, train/val/test)

Real prior runs from this project: Lipari, Stromboli, Pokhara,
Annapurna, Vanceburg (KY), Clintonville (Columbus OH), Empire State
Building, Kahoolawe, the Ozarks.
```

This is a demo, so this confirmation doubles as the audience-facing
"here's what's ready" moment — don't skip it just because the defaults
already work silently.

## Demo venue — "here", "current location", "this building"

The live demo takes place at the **Energy Advancement and Innovation
Center (EAIC)**, Ohio State University, West Lane Avenue, Columbus,
OH 43212, at **40.00604, -83.03490**
([Google Maps](https://www.google.com/maps/place/Energy+Advancement+and+Innovation+Center/@40.0058948,-83.0374756,17z)).

When the user says "here", "current location", "my location", "where
we are", "this building", "the venue" or "EAIC", they mean this
place. Don't ask. Pass `"here"` to the commands:

```bash
scripts/geoai-python -m geoai_datacubes cube "here"
```

`here`, `current location`, `my location`, `our location`, `where we
are`, `this building`, `the venue`, `eaic` and the full building name
are aliases in `.geoai-places.json` (repo root) that map straight to
the coordinates above, with no geocoder call. For other phrasings pass
`"40.00604, -83.03490"`: coordinates are used as given.

The default 2 km radius around it covers most of main campus, the
Olentangy River and Ohio Stadium. NAIP (1 m, US) is available here.

## Gazetteer — islands to recognize without "in Sicily, Italy" etc.

Geocoding a bare short name like "Lipari" or "Catalina" can resolve
to the wrong place, or fail outright, because these aren't the only
things on Earth with that name. Feed the geocoder the disambiguated
form below instead of the bare name the user typed — same
`resolve_aoi`/`Nominatim` flow as any other place, just with better
input:

| User says | Geocode as |
|---|---|
| Lipari | `Lipari, Sicily, Italy` |
| Vulcano | `Vulcano, Sicily, Italy` |
| Salina | `Salina, Sicily, Italy` |
| Stromboli | `Stromboli, Sicily, Italy` |
| Panarea | `Panarea, Sicily, Italy` |
| Filicudi | `Filicudi, Sicily, Italy` |
| Alicudi | `Alicudi, Sicily, Italy` |
| Favignana | `Favignana, Sicily, Italy` |
| Levanzo | `Levanzo, Sicily, Italy` |
| Marettimo | `Marettimo, Sicily, Italy` |
| Capri | `Capri, Campania, Italy` |
| Procida | `Procida, Campania, Italy` |
| Catalina | `Santa Catalina Island, California, USA` |

Groupings, so a request for "the Aeolian Islands" or "the Egadi
Islands" expands sensibly instead of needing every name spelled out:

- **Aeolian Islands** (Sicily) — Lipari, Vulcano, Salina, Stromboli,
  Panarea, Filicudi, Alicudi (the 7 inhabited/named islands; tiny
  Basiluzzo next to Panarea is sometimes counted as an informal 8th
  — skip it unless asked specifically).
- **Egadi Islands** (Sicily) — Favignana, Levanzo, Marettimo.
- **Bay of Naples islands** (Campania) — Capri, Procida (Ischia is
  the third well-known one in this group but isn't in the list
  above — geocode as `Ischia, Campania, Italy` if asked).
- **Catalina** (California) — `Santa Catalina Island` specifically;
  "Catalina" alone is ambiguous (there's a Santa Catalina in Arizona,
  one in Panama, and others).

"Get me imagery over all the Aeolian Islands" means one fetch per
island (they're spread over ~1200 km², too far apart for one 2 km-
radius AOI to cover more than one) — say so and run them as a batch
rather than silently picking just one.

**Voice input garbles these names** (this project is used as a
voice-driven demo, per memory) — "Alicudi" has come through
transcribed as "Alikudi", for instance. If an unrecognized place name
is a close phonetic match to one of the names above (off by a
letter or two, or a plausible respelling), treat it as that place
rather than stopping to ask — but say which one you matched it to,
so a genuine mishear is easy to catch and correct rather than
silently fetching the wrong island. This is necessarily a soft
judgment call, not a lookup table — new near-miss spellings will keep
showing up and can't all be enumerated in advance.

---

## Default 0 — use the `geoai-cubes` conda env, always

This repo was developed and tested against a pre-built conda env
named `geoai-cubes` (built by the `mamba create` recipe
in `docs/install.md` / `skills/00_bootstrap.md`). It already has
`geoai_datacubes`, `rasterio`, `affine`, `geopy`, `pystac_client`,
`planetary_computer`, and everything else this repo needs. Use it —
don't fall back to the base/system Python and start ad-hoc
`pip install`-ing things one error at a time.

The trap: `conda activate geoai-cubes` frequently **silently no-ops**
when run from a non-interactive shell (the kind agent tools use) —
conda's shell hook needs to be sourced first, and if it isn't, the
`activate` call fails quietly and everything after it just runs on
whatever Python was already active. A guard like
`conda activate geoai-cubes 2>/dev/null || true` makes this worse,
not better — it swallows the failure and every subsequent command
silently runs against base Python, which is missing half of what
this repo needs. That mismatch is what produced most of the
`ModuleNotFoundError`s and version-clash errors seen in earlier demo
prep — not real bugs in the packages, just the wrong interpreter.

The reliable fix is to skip `activate` entirely and call the env's
binaries by absolute path — and to do that through the checked-in
`scripts/geoai-python` wrapper rather than inlining the same
resolution logic (`PY=...; [ -x "$PY" ] || ...`) in every command.
Two reasons for the wrapper specifically, not just the absolute path:

1. It's one line instead of three, so it doesn't eat context budget
   re-deriving the same fallback logic every time a command needs it.
2. **Every command sharing one exact shape is what lets a permission
   allowlist actually match.** This bit demo prep once already:
   `.claude/settings.json` had approved patterns for bare
   `python -c "..."`, then every sniff command got rewritten to the
   inline `PY=...` form to fix the wrong-interpreter bug — which
   changed each command's literal shape, so none of the old
   approvals matched anymore and *every* command started prompting
   again, on a session that had previously run smoothly. Fixing one
   correctness bug quietly reintroduced a UX one. Routing everything
   through `scripts/geoai-python` avoids that trap going forward:
   there's exactly one shape (`scripts/geoai-python ...`) to approve,
   once, ever.

```bash
scripts/geoai-python -m geoai_datacubes <command> ...   # the normal case
scripts/geoai-python scratch/one_off.py                 # only for requests no command covers
```

The first-turn `sniff` (AGENTS.md Step 1) checks the interpreter and
also that Python uses **this checkout's** code (the `package:` line).
On the demo laptop the `geoai-cubes` env has an editable install that
points at a different checkout
(`~/Documents/buckAI_observatory/Website/Github/geoai-datacubes`).
`python -m geoai_datacubes` run from the repo root still uses this
checkout, because Python looks in the current folder first. A script
in `scratch/` does not: it imports the other copy unless run as
`PYTHONPATH=. scripts/geoai-python scratch/x.py`.

If no `geoai-cubes` env exists on a given
machine, the wrapper falls back to `python3` with a warning and you should go to
`skills/00_bootstrap.md` to sniff/build the env properly — don't
patch around a missing env with piecemeal `pip install`s in whatever
Python happens to be active.

**Write one-off demo scripts to `scratch/` as real files, never as a
heredoc piped into `scripts/geoai-python`.** Two separate reasons,
both already hit once in this project:

1. `scratch/` (inside the repo) instead of an external scratchpad
   path — some session/sandbox configurations don't trust paths
   outside the project directory even for a session's own designated
   temp/scratchpad location, and reject the write with something
   like "Path is outside allowed working directories". `scratch/` is
   gitignored, so nothing written there needs cleanup or risks
   getting committed.
2. A real file via the Write tool, not `scripts/geoai-python <<'EOF'
   ... EOF`, even though the heredoc feels quicker. A heredoc's
   *content* is part of the Bash command text, and Python syntax that
   mixes braces with quotes — any dict/set literal, e.g.
   `{'minx': 14.6, ...}` for a bbox — can trip a "possible shell-
   expansion obfuscation" heuristic in the permission layer, prompting
   for approval on a command that never previously needed it. That's
   a separate, legitimate security check (unlike the allowlist-shape
   issue above) and shouldn't be routed around — avoid triggering it
   at all by keeping script content in an actual file. The command
   that runs it then stays as simple and consistent as everything
   else in this skill:

```bash
scripts/geoai-python scratch/alicudi_fetch.py
```

## Default 1 — "get me the latest Sentinel-2 image over X" → `cube`

Interpret without asking: a 2 km radius around X, the least cloudy
scene of the last 24 months, and Copernicus DEM alongside unless the
user asked for imagery only. One command does all of it:

```bash
scripts/geoai-python -m geoai_datacubes cube "Panarea"
scripts/geoai-python -m geoai_datacubes cube "Panarea" --radius-km 5
scripts/geoai-python -m geoai_datacubes cube "Panarea" --missions Sentinel-2      # imagery only
scripts/geoai-python -m geoai_datacubes cube "here" --missions Sentinel-2,Copernicus-DEM,Dynamic-World --radius-km 1 --tiles
```

It finds the place, fetches each mission, fuses them into
`data_<place>/<place>_cube.tiff`, writes QGIS styles and a QGIS
project (`<place>_cube.qgs`), cuts tiles if asked, and prints the time
of each step. Optical missions are fetched with their red, green and
blue bands (Sentinel-2: B04, B03, B02, B08, SCL). The missions' own
default bands leave out green and blue, which is why earlier demo
cubes had no natural-colour view.

Don't hand-write this fetch. Hand-written versions failed four ways
in this project: a wrong mission key (`COP30`), wrong band codes
twice (`["red","green","blue"]`, then `["visual"]`), and `roi` passed
as a GeoJSON polygon instead of a bbox list. If a request needs
something `cube` can't do, use `skills/20_build_cube.md`. If it is a
demo need that will recur, add an option to `geoai_datacubes/cli.py`.

Tested 2026-09-27 at the venue, 2 km radius, on a slow connection
(0.6 MB/s): Sentinel-2 11 s, DEM 3 s, fuse + styles + tiles under 1 s.

**NAIP (US aerial photos) needs `--resolution 1`**; the default 10 m
throws away what makes NAIP worth showing. Keep the radius small
(0.5 km gives a 1000 × 1000 px image). A state is flown about every
two years, so pick a year with `--year`; if that year has no flight
the fetch fails and the neighbouring year usually works:

```bash
scripts/geoai-python -m geoai_datacubes cube "here" --missions NAIP --year 2023 --radius-km 0.5 --resolution 1
```

At the venue NAIP exists for 2011, 2013, 2015, 2017, 2019, 2021 and
2023; 2011 took 11 s and 2023 (0.3 m source) 20 s at 0.5 km radius.

## Default 2 — "open it" / "show me" → QGIS, unasked

Open results in QGIS as soon as they're ready, and read later "open
it" / "show me" as QGIS too. Open the `.qgs` project the command
printed, not the GeoTIFF:

```bash
scripts/qgis data_here/here_cube.qgs
```

The project opens the cube once per view (Default 3), in the cube's
own CRS and zoomed to it, so there is no CRS dialog. Opening the
GeoTIFF on its own shows only the main view, from the `.qml` file
next to it.

`scripts/qgis` starts native ARM64 QGIS 3.44 from the `qgis` conda
env with that env's variables set. Don't use
`/Applications/QGIS-LTR.app` (an x86_64 build under Rosetta) or
`open -a .../envs/qgis/QGIS.app` (skips the env variables, so QGIS
shows "Authentication System: DISABLED"). QGIS can't live in
`geoai-cubes`: it needs Python 3.12 or newer and that env is on 3.11.

For a GeoTIFF that didn't come from `cube` (an older run, a single
mission's file), write the styles first:

```bash
scripts/geoai-python -m geoai_datacubes style path/to/file.tiff
```

## Default 3 — which views a cube gets

Decided per band from `MISSION_PROFILES`, so mixed cubes work:

| Bands in the cube | View in the project | Shown at start |
|---|---|---|
| red, green and blue of an optical mission (`TRUE_COLOR` in `geoai_datacubes/viz/bands.py`) | natural colour, 2–98 % stretch per channel | yes |
| elevation (DEM and similar) | QGIS's own hillshade, computed live from the DEM band; no extra file | yes |
| class bands (SCL, land cover) | legend with colour-blind-safe colours; every label includes its class code | no, tick it in the Layers panel |
| none of the above (e.g. only AlphaEarth) | colour ramp of band 1 | yes |

The natural-colour layer lies above the hillshade: untick it to see
the relief. A cube without red, green and blue gets no RGB view,
since any three other bands would make a meaningless picture. Named
legends exist for Sentinel-2 SCL, ESA WorldCover and Dynamic World;
other class bands get "class N" labels (add a legend to
`viz/bands.py` if a demo uses one often). A hillshade GeoTIFF for
figures outside QGIS: `... hillshade path/to/dem.tiff`.

## Default 4 — "create training tiles"

`cube ... --tiles`, or for an existing cube:

```bash
scripts/geoai-python -m geoai_datacubes tiles data_here/here_cube.tiff
```

Demo defaults: 128 px tiles, 25 % overlap, random split, 80/10/10.
Random, not the package's `block` split, because on a small demo area
`block` can leave val or test empty (seen on Lipari). If the user asks
for leakage-safe splits, pass `--split block` and warn that a small
area may leave a split empty. The command prints the tiles per split
and warns when one is empty. For another overlap pass e.g.
`--overlap 0.5`; the stride follows from it.

## Default 5 — "quality report" / "how good is this data"

```bash
scripts/geoai-python -m geoai_datacubes quality data_here/here_cube.tiff
```

Each band is reported under its kind from `MISSION_PROFILES`: optical
statistics with NDVI from each mission's own red/near-infrared pair
(Sentinel-2 B04/B08, Landsat B04/B05), SAR separately in dB, class
histograms (named for SCL, WorldCover and Dynamic World), relief for
elevation bands, and min/max/mean for anything else. The score is
averaged over whichever of cloud cover, completeness, haze and terrain
the cube has. The command gives numbers only: add two or three
sentences on what they mean for the user's purpose.

## Default 6 — land cover defaults to Dynamic World

**LULC default is `Dynamic-World`**, Google's own land-cover product.
It comes through Earth Engine, which works with the configured
`EARTHENGINE_PROJECT` as of 2026-09-27.

**Keep Dynamic World requests to a 1 km radius.** At 2 km Earth Engine
refuses with "User memory limit exceeded" (tested 2026-09-27 at the
venue with 24-, 6- and 1-month windows); at 1 km it works. `cube`
then prints `FAIL Dynamic-World` and carries on with the other
missions. For larger areas use `ESA-WorldCover`.

If an Earth Engine call fails mid-demo (403, `EEException`, expired
login), don't debug it live: switch to `ESA-WorldCover` (no login
needed), say that you switched and why, and fix the login afterwards
per `skills/30_auth.md` §3.1.

## Default 6b — AlphaEarth: change map and "places like this"

`AlphaEarth` is Google DeepMind's AlphaEarth Foundations output: for
every 10 m pixel and every year, 64 numbers (bands `A00`–`A63`)
summarising that place from Sentinel-1/2, Landsat and other inputs.
The 64 numbers of a pixel form a vector of length 1, so the dot
product of two pixels is their similarity (1 = same kind of place).
Earth Engine only.

**Change since 2017** ("how has this area changed", "difference between
the oldest and newest AlphaEarth"):

```bash
scripts/geoai-python -m geoai_datacubes embed-change "here"
scripts/qgis data_here/alphaearth_change_2017_2025.qgs
```

Fetches 2017 and the newest year, and maps 1 − similarity per pixel
(0 = unchanged, higher = changed more), dark to bright. Tested at the
venue, 2 km radius: 69 s, because each year downloads as 4 tiles. The
bright patches are the new buildings and construction sites of the
west-campus Innovation District around the venue.

**Places like this** ("find places that look like Ohio Stadium"):

```bash
scripts/geoai-python -m geoai_datacubes embed-similar "here" --at "Ohio Stadium, Columbus"
```

Colours every pixel by similarity to the reference point; only the
most similar 10 % light up. The reference must lie inside the area.
Pass an AlphaEarth GeoTIFF instead of a place to reuse a download
(0.5 s instead of ~35 s). With the stadium as reference, the stadium
itself lights up most, then big flat roofs, parking lots and highways.

AlphaEarth can also go into a cube (`cube ... --missions
Sentinel-2,AlphaEarth`). There is one image per year, dated 1 January,
so the time window must contain one: the default 24 months does, 12
months doesn't and fails with "Band pattern 'A00' was applied to an
Image with no bands". Don't show the 64 bands as RGB. Beyond the
demo, they are for training a small model (logistic regression,
XGBoost) with far fewer labels than raw bands need.

Known flaw: at 2 km radius about 2 % of pixels along the outer edges
are missing (a seam in the tiled Earth Engine download, present in the
raw files). They show as white notches at the map edges.

## Default 7 — zoom

The `.qgs` project opens zoomed to the cube. When a layer is added to
a QGIS window that already has layers, there's no command-line fix:
reopen the project, or right-click the layer → "Zoom to Layer".

---

## Known environment gotchas (don't rediscover these)

- `fetch_sentinel_data(..., max_cloud_coverage=...)` takes a
  **fraction (0-1), not a percentage**. Passing `100` doesn't error —
  it silently becomes `cloud<10000%`, a no-op filter. Harmless in
  practice because earthsearch still ranks by cloud cover internally
  and the top candidate is picked regardless, but pass `1.0`
  deliberately if "no filter, just the cleanest scene" is the intent,
  or a real fraction like `0.2` for "under 20% cloud".
- Keyword args are `roi=` and `save_folder=` — not `aoi=` /
  `output_dir=`.
- `fuse_response_tiffs(inputs, output_path=...)` — the keyword is
  `output_path`, and the call **returns a dict** (`bands`, `shape`,
  `crs`, `transform`, `path`), not a bare path string. Use
  `result["path"]` if the string is needed downstream.
- `fetch_sentinel_data(...)` returns a **tuple** `(data, final_bands)`
  — not a dict. Only `fuse_response_tiffs` returns a dict with a
  `["path"]` key; don't carry that pattern over to `fetch_sentinel_data`
  calls, it'll `TypeError` on the tuple.
- There is no `fetch_copernicus_dem` (or any per-mission fetch
  function). Every mission, DEM included, goes through the same
  `fetch_sentinel_data(mission=..., bands=..., time_range=..., roi=...,
  save_folder=...)` — for `Copernicus-DEM` pass `bands=["DEM"]` (or
  `None` for the default) and still pass some `time_range` tuple even
  though the static mosaic ignores it (the parameter is positional/
  required regardless of mission).
- `fuse_response_tiffs` and `resolve_aoi` live in
  `geoai_datacubes.preprocessing` and `geoai_datacubes.fetch`
  respectively — there is no `geoai_datacubes.fuse` module. (`from
  geoai_datacubes.fetch import MISSION_PROFILES` does work, it's
  re-exported there — that one's fine.)
- `ModuleNotFoundError` for `rasterio`, `geoai_datacubes`, `geopy`,
  etc., or a `rasterio.transform.from_bounds` crash
  (`TypeError: No '__dict__' attribute on 'Affine' instance...`) —
  before troubleshooting versions, check you're actually going
  through `scripts/geoai-python` and not bare `python` (see Default
  0). Every one of these errors seen while prepping this skill turned
  out to be that, not a real package incompatibility.
- Getting hit with a wall of permission prompts for commands that
  worked fine minutes earlier is usually the same class of problem
  as the one above, one level up: something changed a command's
  literal shape (retyped a python one-liner slightly differently,
  added a variable assignment, whatever) so it no longer matches an
  already-approved pattern in `.claude/settings.json`, and every
  occurrence now reads as new. Keep commands going through
  `scripts/geoai-python`/the other `scripts/*.py` entry points
  consistently rather than improvising equivalent-but-differently-
  shaped one-liners, and this mostly doesn't come up.
- Geocoding: `geopy`'s `Nominatim` is already in the `geoai-cubes`
  env — no install needed there. Prefer it over hardcoding
  coordinates, which silently go stale or wrong the next time
  someone asks for a different place.
- PyQGIS (`from qgis.core import ...`) is **not installed** in
  `geoai-cubes` (it exists only inside the separate `qgis` env) — `ModuleNotFoundError` every time. Don't
  attempt programmatic QGIS project scripting; use file-based
  approaches instead (`.qml` sidecars with the same basename as the
  raster, hand-written `.qgs` project XML when layers genuinely need
  grouping, or plain `scripts/qgis <files>`).

## Default 8 — Report timing for every task

Print elapsed time at the end of every fetch, fuse, tile, or open-in-QGIS
step. The `geoai_datacubes` commands print their own per-step `timing:`
table; copy those numbers. For the total, run `date +%s` as your first
action on a request and again after opening QGIS, and report the
difference. Two separate numbers:

1. **Claude response time** (wall-clock time from user's message to your
   reply going out) — this includes both your own processing and the
   time `geoai-datacubes` spent in the background.
2. **Subagent/background process times** (if any) — when work was
   delegated to a background agent, report the specific timing that agent
   measured (fetch time, fusion time, tiling time, etc.) so the user can
   see what portion of the Claude response time went to each step.

Example format:

```
Sentinel-2 fetch: 45.2s
Copernicus DEM fetch: 23.1s
Fusion: 8.3s
Opened in QGIS: 2.1s
━━━━━━━━━━━━━━━━━
Total: 78.7s (from your request to QGIS showing the result)
```

When a fetch/fuse is delegated to a background agent (running in parallel
while you wait), report the background agent's result the moment it lands,
with those same per-step timings. When the user asks something like:
*"download imagery and DEM over X, create training data, and open in
QGIS"*, they want to know the total wall-clock time from that message to
seeing the result displayed. Report it clearly.

## Handoff

- Demo request is really "build me a cube" with the defaults above
  substituted in → `skills/20_build_cube.md` for the actual fetch +
  fuse.
- User wants to know what's available before picking a place/mission
  → `skills/10_capabilities.md`.
- A fetch fails on auth mid-demo → `skills/30_auth.md`.
