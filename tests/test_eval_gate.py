"""
CI eval gate — Phase 4.

Reads evals/results_latest.json (produced by evals/run_evals.py) and fails
the test suite if any metric is below threshold.

This test is intentionally NOT async — it just reads a file.  Run the eval
script first, then run pytest.  In CI the workflow is:

    python evals/run_evals.py   # exits 1 if below threshold
    pytest tests/test_eval_gate.py

The test provides a human-readable failure message in pytest output so the
CI log is immediately useful.
"""
import json
import pytest
from pathlib import Path

RESULTS_PATH = Path(__file__).parent.parent / "evals" / "results_latest.json"


@pytest.fixture(scope="module")
def results():
    if not RESULTS_PATH.exists():
        pytest.skip(
            "evals/results_latest.json not found — run `python evals/run_evals.py` first."
        )
    with open(RESULTS_PATH) as f:
        return json.load(f)


def test_classifier_precision_meets_threshold(results):
    """Classifier precision must be >= threshold defined in evals/thresholds.json."""
    score     = results["classifier_precision"]
    threshold = results["thresholds"]["classifier_precision"]
    assert score >= threshold, (
        f"Classifier precision {score:.4f} is below threshold {threshold}. "
        f"Check evals/results_latest.json for per-entry breakdown."
    )


def test_entity_f1_meets_threshold(results):
    """Entity extractor micro-F1 must be >= threshold defined in evals/thresholds.json."""
    score     = results["entity_f1"]
    threshold = results["thresholds"]["entity_f1"]
    assert score >= threshold, (
        f"Entity F1 {score:.4f} is below threshold {threshold}. "
        f"Check evals/results_latest.json for per-entry breakdown."
    )


def test_all_gates_passed(results):
    """Convenience test — fails if any gate failed, with a summary message."""
    failures = [
        f"{k}: {results[k]:.4f} < {results['thresholds'][k]}"
        for k, passed in results["passed"].items()
        if not passed
    ]
    assert not failures, "Eval gate failures:\n  " + "\n  ".join(failures)
