# Provider trade-offs: convenience vs throughput at scale

The top-level [README](../README.md#data-providers--when-to-use-which) has
a capability matrix -- which provider serves which mission, which need
credentials, which has server-side band math. This document covers the
**other** axis users hit as soon as they go beyond a Colab demo:
**throughput**. The same provider that wins for one AOI on a laptop can
lose by an order of magnitude on a continent-scale workflow.

Recommendations near the bottom; the reasoning lives in the per-provider
sections.

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
