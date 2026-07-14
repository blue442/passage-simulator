# CLAUDE.md

Sail passage simulator. Vision and phases: PLAN.md. Workflow and ticket protocol: EXECUTION.md.

## How to work in this repo

- Work proceeds ticket-by-ticket from `tickets/phase-N.md`. Pick the next unblocked ticket unless told otherwise; finish with its `Verify:` command and the full test suite passing.
- Files in `specs/` and code blocks marked `# CONTRACT` are frozen interfaces. Do not modify them in an implementation session; escalate instead (see below).
- The simulation engine (`backend/engine/`) must stay pure (no I/O) and deterministic. The replay test is sacred: if it breaks, stop and escalate, never "fix" it by loosening the assertion.
- Constants marked `NEEDS-JUDGMENT` get placeholder values and a config entry; do not tune them yourself.

## Escalation protocol

If you are running on a smaller model (e.g. Sonnet) and you hit any trigger in EXECUTION.md ("Escalation triggers": determinism risk, contract changes, numerical weirdness, two failed fix attempts, judgment calls, cross-boundary refactors):

1. First choice: spawn a subagent with `model: "opus"` (or `"fable"`) scoped to the specific design/debug question, apply its answer, and record the consult in the ticket file.
2. If the whole ticket exceeds the current model: stop, write the blocker under `## Blocked` in the ticket file, and tell the user to rerun after switching models with `/model opus`.

Do not attempt a third fix after two failed attempts on the same failure. Do not improvise interface changes to route around a contract.
