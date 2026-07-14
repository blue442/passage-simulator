# Passage Simulator: Execution Plan

> Execution note: this is the vision document. How it gets built, including the model-tiered AI workflow (Sonnet implementation sessions, Opus/Fable spec sessions and escalation), is in EXECUTION.md.

A web-based sail passage simulator for honing ocean passage-planning skills. Think ocean race tracker meets Windy, with an Oregon Trail heart: a simulated boat sails real-time through real current weather, you check in once or twice a day, read the captain's log of what happened since you left, study the forecast, and issue new orders.

## Vision (as agreed)

| Decision | Choice |
|---|---|
| Time model | Real-time 1:1. A 10-day passage takes 10 real days. |
| Helm model | Standing orders: course/waypoints, sail plan, and conditional rules ("if TWS > 25kt for 30 min, take a reef and bear away to 150 TWA"). |
| Sim depth | Four modules, each toggleable per passage: (1) navigation and performance, (2) sail plan and trim, (3) Oregon Trail events and attrition, (4) safety and tactics. |
| Boats | Generic cruiser presets first (35ft cruiser, 45ft performance cruiser, cruising cat), with a path to custom boats/polars later. |
| Weather | Open-Meteo APIs are the simulation's ground truth. Real GRIB files (GFS, WaveWatch III) are collected for the *user* to plan with, just like real passage-making. |
| Stack | Python/FastAPI sim engine + Postgres (Supabase), TypeScript frontend with MapLibre GL. |
| Hosting | Vercel from day one (FastAPI as a serverless function + static frontend, free Hobby tier), Supabase free-tier Postgres, simple single-user auth. Revised from Fly.io at the Pre-0.5 gate — see specs/deployment.md. |
| Waters | Global free-form sailing plus a curated featured-passage library. |
| Stakes | Real consequences. Damage cascades, storms can dismast or roll you, passages can end in abandonment or death. Ports of refuge and retirement are options. |
| Alerts | Pull-only in v1. If a gale developed while you weren't watching, you find out at check-in. That's the training. |

## Core Concept: Lazy Catch-Up Simulation

Nothing runs between check-ins. When you open the app, the engine simulates forward from the last simulated timestamp to *now*, in small time steps, using **actual recorded weather** for the elapsed period (Open-Meteo serves recent past hours and previous model runs). This means:

- No 24/7 background worker; the server can sleep.
- The weather your boat experienced is what really happened at that position and time.
- The sim is deterministic: weather responses are cached, and the event RNG is seeded per passage, so any catch-up can be replayed identically (essential for debugging and for the post-passage debrief).

The one wrinkle: the boat's future positions depend on weather, and weather queries depend on position. The engine resolves this by stepping: integrate motion in ~10-minute steps, sampling weather (fetched in hourly/tile batches and interpolated) at the boat's current position each step.

## Architecture

```
frontend/  (Vite + TypeScript + MapLibre GL)
  Tracker map · Captain's log · Instruments · Forecast/GRIB viewer · Orders console

backend/   (FastAPI, Python, uv)
  api/            REST endpoints: passages, check-in, orders, weather, gribs
  engine/         time-stepped simulator (pure functions, no I/O)
    motion.py     polars, leeway, wave drag, current set/drift
    orders.py     standing-orders rules engine
    events.py     condition-driven hazards, damage states, attrition
    resources.py  water, provisions, power, crew fatigue
  weather/        Open-Meteo client + Postgres response cache (forecast, marine, past hours)
  gribs/          NOAA NOMADS subsetting/download, decode (cfgrib) to JSON grids for display
  geo/            land mask (GSHHG coastline) for grounding checks, rhumb/great-circle math
  db/             Postgres: passages, boats, track points, log entries, orders, events, weather cache
```

**Key design decisions**

- **Engine is pure and deterministic.** `engine/` takes (state, weather samples, orders, seed) and returns (new state, log events). All I/O lives outside it. This makes it unit-testable with synthetic weather (e.g., "does the reef rule trip in a modeled squall?") and makes replay/debrief trivial.
- **Two weather planes, on purpose.** The engine's truth (Open-Meteo) and the user's planning data (GRIBs you can download and open in the app, or in qtVlm/XyGrib if you like) are different views of similar models — exactly the epistemic situation of a real skipper. Your plan is only as good as your forecast reading.
- **Standing orders as structured rules, not free text.** JSON rules (`condition → action`) built in a UI: conditions over TWS/TWA/gusts/wave height/barometer/time/position, actions over course, sail plan, tactics (heave-to, run off). The log narrates when and why each rule fired.
- **Events are condition-driven, not random.** Hazard rates scale with what you're doing wrong: overcanvassed in 30kt raises gear-failure odds; days of high fatigue raise mistake odds; ignored chafe becomes a torn sail. Oregon Trail narration, actuarially honest underneath.
- **Serverless-friendly by construction.** The lazy catch-up design means nothing runs between check-ins, which is exactly the shape serverless wants: FastAPI runs as a Vercel function, Supabase Postgres holds all state, and catch-up simulation is chunked so no single request outruns a function's time budget (specs/deployment.md). Single user, modest writes, zero ops, near-zero cost.

## Phases

### Phase 0: Scaffold and pipeline
uv project + pyproject, FastAPI skeleton, Vite/TS/MapLibre frontend shell, Vercel two-project deploy (API function + static frontend) with Supabase Postgres wired and a keep-alive cron, single-user token auth, `.env.example`, README per global conventions. **Exit:** deployed hello-world map you can log into from your phone, with a proven database connection.

### Phase 1: Core engine MVP
Boat presets with polar tables; Open-Meteo client with caching (wind, gusts, pressure, waves); time-stepped simulator with simple heading/waypoint orders; great-circle/rhumb movement with current set; land mask grounding check; track + log persistence; lazy catch-up on check-in. **Exit:** create a passage via API, come back 12 hours later, see a believable track and hourly conditions log. Engine has unit tests against synthetic weather.

### Phase 2: The check-in experience
Race-tracker map (track line, fixes, wind barbs along track, destination), instruments panel (position, COG/SOG, TWS/TWD, waves, barometer with trend), chronological log since last check-in, passage-creation flow (start/destination, boat, module toggles, difficulty), waypoint/course orders UI. **Exit:** the full daily loop works end-to-end in the browser and reads well on a phone.

### Phase 3: Standing orders and sail plan
Rules engine; sail inventory (main with reef points, headsail options, storm sails) with polar modifiers per sail state; wrong-sail penalties; orders console with rule builder; log narration of rule firings and sail changes. **Exit:** you can go to sleep with "reef at 25, shake out at 18" set and wake up to a log showing it happened.

### Phase 4: Weather planning tools
GRIB collection per passage (GFS + WW3 subsets from NOMADS for your route's bounding box, on demand at check-in), in-app wind/wave field overlay on the map with a forecast time slider, route meteogram (conditions along your intended track over the next 5 to 7 days), GRIB file download, departure-window view for pre-departure planning. **Exit:** you plan tomorrow's orders from the same GRIBs a real skipper would pull.

### Phase 5: The Oregon Trail layer
Event engine (gear failure, chafe, sail damage, fouled prop, crew injury/seasickness, leaks); damage states with repair choices costing time/spares; provisions, water, fuel, battery budgets; crew fatigue affecting decision quality and event odds; safety tactics (heave-to, run off, lie ahull, bare poles) with real effects; ports of refuge and diversion; abandonment and death endings; difficulty settings; the narrative voice. **Exit:** an ironman gale passage is genuinely tense, and the log tells the story.

### Phase 6: Tides, currents, featured passages
NOAA CO-OPS tidal predictions and currents for US coastal waters; ocean surface currents from Open-Meteo's marine current fields (Gulf Stream routing becomes real); curated featured-passage library (e.g., Newport–Bermuda, Chicago–Mackinac, a transatlantic) with hand-checked data quality and stated learning goals per passage. **Exit:** a Gulf Stream crossing rewards current strategy; tide gates matter on coastal hops.

### Phase 7: Polish and debrief
Post-passage debrief: replay your track against the weather that actually occurred, compare against an optimal-routing baseline, decision-by-decision review; custom boat import (your own polars); tracker-aesthetic polish; performance passes. **Exit:** finishing a passage teaches you something concrete about your planning.

## Risks and open questions

- **Open-Meteo marine coverage/latency.** Wave and current fields have coarser resolution near coasts; verify past-hours availability for marine variables early (Phase 1 spike). Fallback: ERA5-recent archive endpoint.
- **Weather API volume.** A 12-hour catch-up at 10-min steps is ~72 steps, but batched hourly fetches along the track keep it to a handful of requests. Cache aggressively.
- **Global tidal currents don't exist freely.** Scope tides to NOAA waters (plus ocean currents globally) and say so in the UI, rather than pretending.
- **Land mask resolution.** GSHHG intermediate resolution is fine offshore; coastal featured passages may need the high-res set for honest grounding checks.
- **Realism tuning.** Event rates and polar modifiers will need iteration against your judgment as a sailor; build tuning constants into config, not code.

## Suggested first milestone

Phases 0–2 form the minimum satisfying product: a real boat on a real ocean in real weather that you can check in on twice a day from your phone. Everything after that deepens the game without changing the daily loop.
