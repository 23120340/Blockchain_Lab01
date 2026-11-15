"""End-to-end T1-T8 (và X1-X3) chạy qua pytest: python -m pytest tests"""
import pytest

from tests.check_determinism import compare_two_processes
from tests.scenarios import SAFETY_CHECKS, SCENARIOS, SWEEP, failed, run_config


@pytest.mark.parametrize("test_id,name", [(s[0], s[1]) for s in SCENARIOS])
def test_scenario(test_id, name):
    _, _, summary, verdict = run_config(name)
    assert verdict["pass"], f"{test_id} {name}: {failed(verdict)}"
    assert summary["min_correct_height"] >= summary["target_height"] > 0


@pytest.mark.parametrize("name,seed", [(n, s) for n, seeds in SWEEP.items() for s in seeds[:6]])
def test_safety_holds_for_other_seeds(name, seed):
    _, _, _, verdict = run_config(name, seed)
    bad = [c for c in verdict["checks"] if c["name"] in SAFETY_CHECKS and not c["ok"]]
    assert not bad, bad
    progress = [c for c in verdict["checks"] if c["name"] == "progress_to_target_height"]
    assert progress and progress[0]["ok"], progress


def test_t8_same_seed_twice_is_byte_identical(tmp_path):
    result = compare_two_processes("t7_byzantine_equivocation", str(tmp_path))
    assert result["identical_log_bytes"] and result["identical_state_hash"], result
    assert result["log_bytes"] > 100_000
