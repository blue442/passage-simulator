import subprocess
import sys

from passage.engine.rng import rng_for_step


def test_same_inputs_produce_same_draws() -> None:
    a = rng_for_step(42, 7, "wind").random()
    b = rng_for_step(42, 7, "wind").random()
    assert a == b


def test_different_step_or_stream_produce_different_draws() -> None:
    base = rng_for_step(42, 7, "wind").random()
    assert rng_for_step(42, 8, "wind").random() != base
    assert rng_for_step(42, 7, "waves").random() != base
    assert rng_for_step(99, 7, "wind").random() != base


def test_deterministic_across_fresh_subprocesses() -> None:
    # The frozen RNG rule explicitly forbids builtin hash() on strings/tuples because it is
    # salted per process; this is the test the spec asks for to guard against that regression.
    code = "from passage.engine.rng import rng_for_step; print(rng_for_step(42, 7, 'wind').random())"
    outputs = {
        subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, check=True
        ).stdout.strip()
        for _ in range(3)
    }
    assert len(outputs) == 1
