# Execution Guide: Model-Tiered Workflow

PLAN.md is the vision. This document is how it gets built by AI coding sessions, mostly on a smaller model (Sonnet), with deliberate checkpoints on a larger model (Opus or Fable). The principle: **large models design and judge; small models implement against fixed contracts and verify with tests.**

## The three session types

### 1. Spec sessions (large model, at each phase gate)
Run on Opus/Fable (`/model opus` or `/model fable`). Happens once at the start of each phase, and once at the end.

Phase-start spec session produces:
- Frozen contracts for the phase: Pydantic models, DB schema migrations, API endpoint signatures, JSON schemas (e.g. the standing-orders DSL). Contracts live in `specs/` and in code as typed interfaces.
- A ticket file `tickets/phase-N.md` breaking the phase into S/M-sized tickets (format below), each with acceptance criteria and a verification command.
- Test fixtures where correctness is subtle: synthetic weather scenarios with hand-checked expected outcomes ("golden tests") that implementation tickets must pass.

Phase-end review session: reads the full diff since the gate, checks contracts weren't drifted, checks determinism/replay still holds, tunes anything flagged `NEEDS-JUDGMENT`, and writes the next phase's spec.

### 2. Implementation sessions (Sonnet, the bulk of the work)
Work one ticket at a time from `tickets/phase-N.md`. Rules:
- Do not modify anything in `specs/` or any file marked `# CONTRACT` without escalating.
- Every ticket ends with its verification command passing, plus the full test suite.
- Mark the ticket done in the ticket file with a one-line note of anything surprising.

### 3. Escalation consults (large model, on demand)
When an implementation session hits an escalation trigger (below), it does one of:
- **Preferred:** spawn a subagent on the larger model for the specific question (the Agent tool accepts `model: "opus"` / `model: "fable"`), apply its answer, and note the consult in the ticket file.
- If the whole ticket is over its head: stop, write the blocker into the ticket file under `## Blocked`, and tell the user to re-run the ticket after `/model opus`.

## Escalation triggers

An implementation session must escalate (not push through) when any of these appear:

1. **Determinism at risk.** Any change touching RNG seeding, weather-cache keys, or step ordering; or a replay test producing a different track than the original run.
2. **Contract pressure.** The ticket can't be completed without changing a schema, interface, or anything in `specs/`.
3. **Numerical weirdness.** Coordinate math near the antimeridian or high latitudes, integration steps that oscillate or blow up, interpolation artifacts at weather-tile boundaries.
4. **Two failed fixes.** The same test has failed after two distinct fix attempts, or tests pass but observed behavior is wrong. Do not attempt a third blind fix.
5. **Judgment calls.** Event probabilities, polar modifiers, narrative voice, difficulty tuning: anything where "correct" means "feels right to a sailor". These are marked `NEEDS-JUDGMENT` in tickets; implement behind a config constant with a placeholder value and leave tuning for a spec session (with Steven in the loop).
6. **Cross-boundary refactors.** Any change spanning `engine/` and `api/` or `weather/` simultaneously beyond call-site updates.

## Ticket format

```markdown
### T1.3 Weather response cache · Complexity: M
Files: backend/weather/cache.py, tests/weather/test_cache.py
Contract: specs/weather-cache.md (key = model,run,var,tile,hour; never overwrite)
Do: <2-6 concrete steps>
Accept:
- Same query twice hits network once (assert via mock transport)
- Cache survives process restart (Postgres-backed)
Verify: uv run pytest tests/weather -q
Escalate if: key schema proves insufficient for determinism (trigger 1/2)
```

Complexity S = one file + test, M = 2-4 files against an existing contract. Anything that would be L means the spec session sliced it wrong: escalate rather than improvise.

## Why the engine architecture already helps

Two decisions in PLAN.md were made with exactly this workflow in mind:

- **The engine is pure.** `engine/` functions take (state, weather samples, orders, seed) and return (new state, events). No I/O means Sonnet can verify any ticket with fast, deterministic unit tests against synthetic weather, which is the feedback loop small models need.
- **Determinism is testable.** A single replay test ("simulate 24h twice from the same inputs, tracks must be identical") acts as a tripwire: if a Sonnet change breaks it, that's an automatic escalation rather than silent corruption.

## Phase gates at a glance

| Gate | Large-model session produces |
|---|---|
| Pre-0 | Repo conventions, CI, `specs/api-skeleton.md`, tickets/phase-0.md |
| Pre-1 | Engine state model, weather-cache contract, orders-v0 schema, golden weather fixtures, tickets/phase-1.md |
| Pre-2 | API contracts for check-in payloads, frontend component map, tickets/phase-2.md |
| Pre-3 | Standing-orders DSL schema (highest-risk contract in the project), rule-semantics golden tests (hysteresis, `FOR 30min` windows), tickets/phase-3.md |
| Pre-4 | GRIB subsetting spec, grid-JSON format for the frontend, tickets/phase-4.md |
| Pre-5 | Event/hazard model design, all `NEEDS-JUDGMENT` constants enumerated for tuning with Steven, tickets/phase-5.md |
| Pre-6 | Tide/current data-source integration spec, featured-passage data format, tickets/phase-6.md |
| Pre-7 | Debrief/replay design (leans hard on determinism), tickets/phase-7.md |

Each phase-end review doubles as the next phase-start spec, so in practice it's one large-model check-in per phase, which matches a "check in with the big model once per phase, Sonnet grinds in between" rhythm.
