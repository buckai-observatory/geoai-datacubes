# Provider trade-offs: convenience vs throughput at scale

The pipeline supports **38 missions** end-to-end (v0.1.0 release: 23;
**+15 v0.2-preview additions on this branch**) across up to **eight
interchangeable providers** — four STAC-based, one commercial, plus
`direct_http` for non-STAC anonymous COGs, `earth_engine` for
Google Earth Engine, `earthdata` for anything hosted by a NASA
DAAC behind Earthdata Login, and `local_files` for the user's own
local rasters (registered at runtime). Five of the eight need no
credentials. The default `PROVIDER = "auto"` routes each mission to
the best free option.

This document covers two axes: **(1) capability** — which provider
serves which mission, which needs credentials, which has server-side
band math — and **(2) throughput** — the same provider that wins for
one AOI on a laptop can lose by an order of magnitude on a
continent-scale workflow.

> **v0.2-preview on this branch (`feature/earth-engine-provider`).**
> Three new provider classes and fifteen new missions land on this
> branch and are documented here alongside the reviewed v0.1.0
> providers. `main` currently ships only the first five providers
> (STAC + direct_http).

---

## Quick capability matrix

The four STAC-based providers plus `direct_http` (unchanged from
v0.1.0):

| | `earthsearch` | `planetary_computer` | `planet` (commercial) | `sentinelhub` (advanced) | `direct_http` |
|---|---|---|---|---|---|
| **Credentials** | None | None | `PL_API_KEY` in `.env` | Free Sentinel Hub OAuth in a `.env` | None |
| **Hosted by** | Element 84 (AWS Open Data) | Microsoft Planetary Computer (Azure) | Planet Labs Data + Orders API | Sentinel Hub Process API | Direct anonymous URLs (GCS, ETH, AWS Open Data) |
| **Sentinel-2 L2A** | ✅ Fast (no sign step) | ✅ | — | ✅ | — |
| **Sentinel-2 L1C** | ✅ | ✅ | — | (not wired) | — |
| **Sentinel-1** | ⚠️ Raw GRD only — ground-range, no native CRS (unusable as-is) | ✅ **RTC** — terrain-corrected & georeferenced | — | ✅ | — |
| **Landsat 8-9 C2 L2** | ⚠️ `usgs-landsat` bucket is requester-pays (anonymous reads fail) | ✅ Same data, served free | — | ✅ | — |
| **PlanetScope (3 m)** | — | — | ✅ 4-band legacy + 8-band SuperDove SR + UDM2 | — | — |
| **NAIP (1 m US aerial)** | — | ✅ | — | — | — |
| **Hansen-GFC** | — | — | — | — | ✅ Only public path (anonymous GCS COGs) |
| **Server-side band math** | No | No | Server-side clip-to-AOI | Yes (evalscripts) | No |
| **Best for** | Sentinel-2 (skip the per-asset sign step) | Sentinel-1 RTC, Landsat, NAIP, MODIS, HLS, ALOS, USDA-CDL, LCMAP, IO-LULC, Chloris-Biomass, 3DEP, JRC-GSW | High-res commercial PlanetScope; users with Planet/NICFI/Education access | Production runs, custom band math, very large ROIs | Missions with no STAC / no auth (Hansen GFC and similar) |

Plus three new provider classes on this branch (**v0.2 preview**):

| | `earth_engine` | `earthdata` | `local_files` |
|---|---|---|---|
| **Credentials** | Google account + GCP project with EE API enabled | Free NASA Earthdata Login + DAAC-app authorization | None |
| **Hosted by** | Google Earth Engine (server-side compute + reproject) | NASA CMR + per-DAAC HTTPS (ASF, ORNL, NSIDC, GES DISC, PODAAC) | User's own local filesystem |
| **Dynamic World** | ✅ Only public host | — | — |
| **JRC-GFC2020** | ✅ Only public host | — | — |
| **MODIS_SR / MODIS_LST** | ✅ **Default on this branch** (server-side sinusoidal-tile mosaicking, closes [Issue #10](https://github.com/buckai-observatory/geoai-datacubes/issues/10)); reprojects to target UTM automatically | — | — |
| **NISAR-L (L-band SAR)** | — | ✅ Only public host (via ASF DAAC) | — |
| **ICESat-2 (ATL03/06/08/13)** | — | ✅ NSIDC DAAC; multi-granule tracks aggregation | — |
| **GEDI L4A / L4B biomass** | — | ✅ ORNL DAAC | — |
| **SWOT L2 HR Raster** | — | ✅ PODAAC | — |
| **CryoSat-2 RDEFT4 sea ice** | — | ✅ NSIDC DAAC | — |
| **Sentinel-5P TROPOMI** | — | ✅ GES DISC (requires `NASA GESDISC DATA ARCHIVE` app) | — |
| **SMAP L3 soil moisture** | — | ✅ NSIDC DAAC | — |
| **GEBCO 2024 bathymetry** | — | — | — (`direct_http`) |
| **Airborne LIDAR / commercial optical / drone imagery** | — | — | ✅ Any locally-stored raster registered via `register_local_mission(...)` |
| **Server-side operations** | Full ImageCollection reductions, per-band scale factors, reprojection, temporal composites | Windowed reads into large HDF5 / GeoTIFF granules; download-and-cache | AOI-window read + reproject to local UTM; mosaic across matching files |
| **Best for** | Dynamic World, MODIS in a target CRS, JRC-GFC2020, and any of hundreds of other EE-native collections | NISAR L-band, GEDI biomass, SMAP soil moisture, ICESat-2, SWOT, CryoSat, TROPOMI, and anything else in the NASA DAAC catalogue | Airborne LIDAR bathymetry / topography, licensed WorldView / Maxar, georeferenced drone RGB-NIR, any per-project raster the user wants to fuse |

See [`providers/earth_engine.md`](providers/earth_engine.md),
[`providers/earthdata.md`](providers/earthdata.md), and
[`providers/local_files.md`](providers/local_files.md) for the full
walkthroughs.

## `PROVIDER = "auto"` routing (the default)

| Mission | Routed to | Why |
|---|---|---|
| `Sentinel-2` / `Sentinel-2-L1C` | `earthsearch` | Faster — no per-asset SAS sign step |
| `Sentinel-1` | `planetary_computer` | Gives you the analysis-ready RTC product |
| `Landsat` / `Landsat-8` / `Landsat-9` | `planetary_computer` | Avoids `usgs-landsat`'s requester-pays bucket |
| `Copernicus-DEM` | `earthsearch` | Both work; ES skips the sign step |
| `Copernicus-DEM-90` | `planetary_computer` | PC-only |
| `ESA-WorldCover` | `planetary_computer` | Earth Search does not host WorldCover |
| `NAIP` | `planetary_computer` | PC is the only public host for NAIP |
| `MODIS_SR` / `MODIS_LST` *(v0.2 preview)* | `earth_engine` | **Changed on branch**: EE handles sinusoidal tile-seam mosaic + reprojection server-side ([Issue #10](https://github.com/buckai-observatory/geoai-datacubes/issues/10)). Old `planetary_computer` path still works via explicit `provider=` override. |
| `HLS_S30` / `HLS_L30` / `JRC-GSW` / `3DEP` | `planetary_computer` | PC-only for these missions |
| `ALOS-PALSAR` / `ALOS-FNF` / `USDA-CDL` / `LCMAP-CONUS` / `IO-LULC` / `Chloris-Biomass` | `planetary_computer` | PC-only |
| `Hansen-GFC` | `direct_http` | Non-STAC anonymous Google Cloud Storage COGs |
| `ArcticDEM` *(v0.2 preview)* | `direct_http` | Non-STAC anonymous AWS Open Data COGs (PGC S3) |
| `GEBCO-2024` *(v0.2 preview)* | `direct_http` | Non-STAC anonymous BODC/CEDA per-tile GeoTIFFs |
| `Dynamic-World` *(v0.2 preview)* | `earth_engine` | Google Earth Engine only |
| `JRC-GFC2020` *(v0.2 preview)* | `earth_engine` | Google Earth Engine only |
| `NISAR-L` *(v0.2 preview)* | `earthdata` | ASF DAAC only; requires NASA Earthdata Login |
| `PlanetScope-4b` / `PlanetScope-8b` | not auto-routed | Commercial — opt in with `PROVIDER="planet"` |
| `Sentinel-5P` | not routed (stubbed) | Sentinel-5P: NetCDF reader pending. |

The output `<Mission>_full_size.tiff` is functionally identical
regardless of provider; the rest of the pipeline (cloud masking, NDVI,
tiling, export) doesn't care which one was used.

Switching to a paid / advanced provider (Sentinel Hub or Planet) needs
a one-time credential setup; see [`credentials.md`](credentials.md).

---

## Earth Search (Element 84, no credentials)

**What it is.** A free STAC API in front of **AWS Open Data buckets** in
specific AWS regions (Sentinel-2 L2A lives in `us-west-2`; other
products vary). When the pipeline "downloads" through Earth Search the
flow is two steps:

  1. STAC search via HTTPS to `earth-search.aws.element84.com`.
  2. `/vsicurl/` byte-range reads of the public S3 object URLs that come
     back. No per-asset signing, no auth headers, no rate-limit
     dashboard.

That simplicity is the entire value proposition. Same Python works on a
laptop in Munich and a Colab in Chicago.

**Where it gets slow.**

1. **Geographic latency.** Each COG byte-range read pays the round-trip
   time to the bucket's region. A single Sentinel-2 L2A cube needs
   hundreds of reads; from Europe to `us-west-2` that's ~150 ms per
   request, and the workload becomes latency-bound rather than
   bandwidth-bound. From a `us-west-2` EC2 / SageMaker instance the same
   workload is bandwidth-bound. **The same line of Python can be ~10x
   slower outside the bucket's home region.**

2. **Anonymous-S3 throttling.** AWS does enforce throttle limits on
   anonymous reads even on Open Data buckets. Authenticated AWS access
   has higher per-account ceilings, and Planetary Computer's
   asset-signing-then-CDN flow hits its own (separate) limits. Many
   concurrent fetches against Earth Search can intermittently 503.

3. **No CDN-like asset caching.** Cold reads are the only reads. Popular
   tiles get no acceleration from a content-distribution layer.

4. **No server-side band math.** Every band you ask for comes back as raw
   COG bytes, even when you only need one composite index over a region.
   For "give me an NDWI of three countries" workflows that's a lot of
   bytes moved for a final answer that's a few MB.

**When it wins.** Single AOIs. Interactive notebooks. Colab demos.
Workflows running inside `us-west-2`. The pipeline's
`PROVIDER="auto"` route picks Earth Search for Sentinel-2 specifically
because at that scale skipping the per-asset sign step is faster than
PC's signing flow.

---

## Microsoft Planetary Computer (no credentials)

**What it is.** A free STAC API plus an asset-signing service. When the
pipeline downloads through PC the flow is three steps:

  1. STAC search via HTTPS to `planetarycomputer.microsoft.com`.
  2. Sign each asset URL via PC's signing endpoint (the pipeline batches
     this).
  3. `/vsicurl/` byte-range reads of the signed URLs, which point at
     Azure Blob Storage backed by **a CDN**.

The per-asset signing step is the extra HTTP hop versus Earth Search.
It is what lets PC put a CDN in front of popular assets.

**Where it wins at scale.**

* **CDN-cached warm reads.** Popular Sentinel-2 tiles, NAIP scenes,
  WorldCover tiles served from PC tend to be warm in the CDN. Repeat
  reads (e.g. the same scene re-tested across model runs) are
  near-instant.
* **Higher per-asset throttle ceilings** than anonymous S3 in the
  shapes typical for ML workloads (many concurrent COG reads).
* **Free egress within Azure.** If you run compute on the
  [Planetary Computer Hub](https://planetarycomputer.microsoft.com/compute)
  or your own Azure VM in the same region as the bucket, the network
  isn't a bottleneck.
* **The only host for several missions.** Sentinel-1 RTC, Landsat C2 L2
  (without the requester-pays bucket headache), NAIP, MODIS, HLS,
  JRC-GSW, 3DEP -- all are PC-only in the pipeline today.

**Where it's slow.** The asset-signing step adds noticeable overhead on
**small** workloads (one AOI, one date) because you pay the signing
round-trip before the first byte of imagery. For interactive demos this
overhead is why the `PROVIDER="auto"` route picks Earth Search for
Sentinel-2 instead.

---

## Sentinel Hub (paid, opt-in)

**What it is.** A commercial Process API that does **server-side**
reprojection, resampling, band-math, and composite generation. The
pipeline submits an *evalscript* that names the inputs, the math, and
the output bands; Sentinel Hub returns a single ready-to-use image.

**Where it wins at scale.**

* **One small image back instead of every raw band.** If your final
  product is a single composite (NDWI, NDVI, RGB, a custom index)
  computed over many AOIs, you avoid moving the underlying raw bytes at
  all. For continental-scale per-pixel index workflows this trade is
  hard to beat.
* **No per-asset COG read latency** -- the latency is bound by the
  upload time of the result, which is tiny by construction.

**The catch.**

* **Processing units (PU) cost real money** beyond a small free tier.
  Heavy use can run into significant dollars per day.
* **Lock-in.** Evalscripts are Sentinel-Hub-specific JavaScript; not
  trivially portable to other providers.

When this is the right answer it tends to be obvious: you know your
output is small per AOI and you have a lot of AOIs.

---

## Planet (commercial, high-res)

**What it is.** Planet's Orders API takes an AOI, a time window, and a
product spec; Planet prepares the delivery (clip, mask, harmonize) and
sends a URL when ready.

**Where it wins.** Sub-3-m PlanetScope and SkySat imagery -- nothing
else in the pipeline goes that fine. The server-side AOI clip saves you
from downloading a whole Planet scene to keep a few hundred metres of
it.

**The catch.** Asynchronous orders -- the wait between submit and ready
is typically minutes, sometimes longer. Commercial licence terms govern
redistribution; the pipeline can't bundle Planet outputs in a public
repo because of that.

---

## `direct_http` (no STAC, anonymous HTTPS)

**What it is.** A small in-tree provider for missions that are *not* in
any STAC catalogue but expose anonymous HTTPS COG URLs directly --
Hansen Global Forest Change on Google Cloud Storage was the reference
case; ArcticDEM v4.1 (PGC AWS Open Data) and GEBCO 2024 (BODC/CEDA
per-tile GeoTIFFs) followed on the v0.2 branch. Planned next
additions: Lang 2023 canopy height and Tolan 2024 1-m CHM. The
pipeline calls a per-mission tile-callback (declared in
`MISSION_PROFILES[<mission>]["providers"]["direct_http"]`) that turns
an AOI bbox into a list of `(URL, band)` tuples; the generic fetcher
then `/vsicurl/`-reads, reprojects, and mosaics them like any other
STAC-served mission.

**Where it wins.** Datasets the broader STAC ecosystem hasn't indexed
yet -- Hansen GFC is widely cited but has never had a public STAC
endpoint; bundling it as a `direct_http` mission lets users pull
forest-loss-by-year rasters into a fused multi-mission cube with the
same `fetch_sentinel_data` API as Sentinel-2 or Landsat. GEBCO 2024
is another textbook fit: BODC's per-tile GeoTIFFs support HTTP
byte-range requests, so a 5-10 km AOI transfers only a few kB from
each 933 MB tile.

**The catch.** No catalogue search -- each mission's tile-callback has
to know the dataset's URL scheme by hand. Acceptable when the
dataset's tile layout is simple (e.g. Hansen GFC's 10° × 10°
NW-corner naming or GEBCO's 8 fixed 90° tiles); awkward when it
isn't. Auth-gated direct downloads (NASA Earthdata Login) belong on
the separate `earthdata` provider, not here.

---

## Direct AWS access (anonymous boto3, no Earth Search)

**What it is.** Skip Earth Search's STAC layer entirely and use a
boto3 client (or the `aws s3 cp` CLI) against the public buckets
directly. Works for `sentinel-s2-l2a`, `usgs-landsat`-equivalent buckets
that allow anonymous reads, and others.

**Where it wins.** Inside AWS, you get native multipart-download
parallelism, free egress to compute in the same region, and you bypass
the latency budget of vsicurl-over-HTTPS-via-STAC. For pre-built
**training-pixel pipelines** running on AWS, this is the right tool.
The data is identical to what Earth Search points at; you're just
saving the indirection.

**The catch.** No catalog / search layer. You need to know the keys
(scene IDs and asset paths). Useful for engineering / production
pipelines, not for exploratory notebooks.

---

## Recommendations by workload shape

| You're doing | Reach for | Why |
|---|---|---|
| **A single Colab demo or laptop run, a few AOIs** | the pipeline's `PROVIDER="auto"` | The convenience-cost-throughput trade-off is dominated by convenience at this scale; you won't notice the difference between providers. |
| **A handful of AOIs from a laptop outside the bucket's region** | `PROVIDER="auto"` (same answer) -- but expect 30 s -- 2 min per S2 cube | Latency-limited regardless of provider. |
| **Tens to thousands of AOIs from inside AWS `us-west-2`** | `PROVIDER="earthsearch"` (or direct anonymous boto3) on EC2 / SageMaker | Free egress inside the bucket's region, anonymous S3 throughput. The whole stack becomes bandwidth-limited. |
| **Tens to thousands of AOIs from inside Azure** | `PROVIDER="planetary_computer"` on the [Planetary Computer Hub](https://planetarycomputer.microsoft.com/compute) or an Azure VM | Free egress inside the bucket's region, signed CDN-cached URLs, batched signing. |
| **Single composites / indices over many AOIs (e.g. NDVI over a continent)** | `PROVIDER="sentinelhub"` with an evalscript | Server-side reduction; you never move the raw bytes for bands you'll average away. |
| **Sub-3 m / PlanetScope** | `PROVIDER="planet"` with `PL_API_KEY` | Only public path to that resolution. |
| **A reproducible pipeline that should run inside CI without auth** | `PROVIDER="auto"` | Earth Search and PC both work without credentials; only the commercial paths require keys. |

## Two concrete optimisations a continental workflow can apply

1. **Move the compute, not the data.** The biggest single throughput
   knob across providers is whether your code runs inside the same
   cloud as the data. AWS Open Data + EC2 `us-west-2` →
   bandwidth-limited. Planetary Computer + Azure → bandwidth-limited.
   Laptop / Colab outside either cloud → latency-limited regardless of
   provider. **A continent-scale fetch from a laptop is going to be
   slow no matter which provider you pick.**

2. **Parallelise at the right granularity.** The pipeline ships
   `geoai_datacubes.fetch.fetch_many_in_parallel(jobs, max_workers=...)`
   precisely for this -- many small concurrent fetches against a single
   provider. ThreadPoolExecutor is the right concurrency primitive
   because the bottleneck is network I/O, not Python compute. Sane
   defaults are 3-8 workers per provider; push higher and you'll start
   to see throttling instead of speedup.
