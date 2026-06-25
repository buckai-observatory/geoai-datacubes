# Credentials & security

The default `earthsearch` and `planetary_computer` providers need
**no credentials at all** and cover everything but PlanetScope and the
advanced server-side band-math route. Skip this entire document unless
you opt into a paid / advanced provider.

## Sentinel Hub (server-side `evalscripts`, very large ROIs)

1. **Register** for a free account at the
   [Copernicus Data Space Ecosystem](https://dataspace.copernicus.eu/).
2. Open the **Sentinel Hub dashboard** at
   <https://shapps.dataspace.copernicus.eu/dashboard/> and go to
   **User settings → OAuth clients → Create new**. Copy the
   **client ID** and **client secret** somewhere safe.
3. Copy the bundled template and paste in your keys:
   ```bash
   cp .env.example .env             # then open .env in your editor
   ```
   ```
   SH_CLIENT_ID=your-client-id-here
   SH_CLIENT_SECRET=your-client-secret-here
   SH_INSTANCE_ID=                  # optional
   ```
4. In `geoai_datacubes/main.py`, set `PROVIDER = "sentinelhub"`.

## Planet Orders API (commercial PlanetScope, ~3 m)

1. **Get an API key** at
   <https://www.planet.com/account/#/user-settings> under
   **API keys** (requires a Planet account; researchers can apply to
   the Education & Research Program for archive access, and
   humid-tropics work can use the free **NICFI** program — both
   surface the same `PL_API_KEY` here).
2. Copy the bundled template and paste in your key:
   ```bash
   cp .env.example .env             # then open .env in your editor
   ```
   ```
   PL_API_KEY=your-planet-api-key-here
   ```
3. In `geoai_datacubes/main.py`, set `PROVIDER = "planet"` and
   `MISSION = "PlanetScope-4b"` (legacy 4-band B/G/R/NIR, archive back
   to ~2016) or `MISSION = "PlanetScope-8b"` (SuperDove 8-band
   CB/B/GI/G/Y/R/RE/NIR, ~2022 onward).
4. Pick a finer resolution — PlanetScope's native ground sampling is
   ~3 m, so `RESOLUTION = 3` is a sensible default.

Under the hood, the `planet` provider uses Planet's **Data API**
(`/quick-search`) to pick the lowest-cloud-cover scene matching your
AOI/dates/instrument, then submits a single-scene **Orders API**
request with server-side clip-to-AOI. The order is asynchronous —
expect a few minutes for the order to reach `success` — and the
pipeline polls automatically (default 60 min timeout, override via
`max_wait_seconds`). The order delivers the analytic-SR COG and a UDM2
raster; both are downloaded, reprojected onto the same UTM grid we use
for Sentinel/Landsat, and written into a multi-band
`<Mission>_full_size.tiff` with descriptions like `"R"`, `"NIR"`,
`"udm2_clear"` — so cloud masking in the tiler flows through
unchanged.

## Security hygiene

The repository's `.gitignore` already excludes `.env`; keep it that
way and **never hardcode keys in source files**. If you ever expose a
secret accidentally, revoke it in the relevant dashboard and create a
new one.

## See also

- [`install.md`](install.md) — the rest of the install + first-run recipe.
- [`providers.md`](providers.md) — trade-offs between providers.
