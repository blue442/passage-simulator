# CONTRACT — see specs/engine-state.md §7 "RNG rule". Unused in Phase 1 (no stochastic draws
# yet); frozen now so Phase 5 events cannot break chunk-invariance.
import hashlib
import random


def rng_for_step(seed: int, step_index: int, stream: str) -> random.Random:
    """Deterministic substream keyed by (seed, step_index, stream). Never advance a single
    running generator across a whole passage -- a fresh substream per (seed, step, stream) is
    what keeps stochastic draws chunk-invariant regardless of how catch-up is chunked.

    Does NOT use the builtin hash() on strings/tuples: that is salted per-process
    (PYTHONHASHSEED) and would make draws differ across process/replay boundaries."""
    digest = hashlib.sha256(f"{seed}|{step_index}|{stream}".encode()).digest()
    substream_seed = int.from_bytes(digest[:8], "big")
    return random.Random(substream_seed)
