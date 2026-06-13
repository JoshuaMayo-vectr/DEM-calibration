"""Phase-7 tests for calibration/screen.py — no LIGGGHTS launches.

The driver is stubbed: runner.evaluate_batch is monkeypatched with an analytic
AoR response, so the sampling, collection, sensitivity and bracketing logic is
exercised in milliseconds. The pure helpers (sample bounds/reproducibility,
canonical round-trip, NaN handling) are tested directly.
"""

import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from calibration import runner, screen  # noqa: E402


# ------------------------------------------------------------- sampling
def test_sample_shape_bounds_reproducible():
    X = screen.sample(40)
    assert X.shape == (40, 3)
    lo = np.array([b[0] for b in screen.SCREEN_PROBLEM["bounds"]])
    hi = np.array([b[1] for b in screen.SCREEN_PROBLEM["bounds"]])
    assert (X >= lo).all() and (X <= hi).all()
    # deterministic for a fixed seed
    np.testing.assert_array_equal(X, screen.sample(40))


def test_rows_to_params_roundtrips_through_canonical():
    X = screen.sample(20)
    for p in screen.rows_to_params(X):
        c = runner.canonical(p)              # must not raise (ranges ⊂ runner.RANGES)
        assert c["fricpw"] == c["fric"]      # walls mirror particle
        assert c["rollfricpw"] == c["rollfric"]


# ------------------------------------------------------------- run / collect
def _fake_result(params, *, aor):
    """Shape one runner.evaluate aggregate dict the way the real driver returns it."""
    canon = runner.canonical(params)
    return {
        "aor": aor,
        "aor_std": 0.5 if aor is not None else 0.0,
        "bulk_density": 780.0 if aor is not None else None,
        "n_ok": 2 if aor is not None else 0,
        "params": canon,
        "trial_dirs": [str(runner.trial_dir(canon, runner.SEEDS[0]))],
    }


def test_run_screen_delegates_to_evaluate_batch(monkeypatch):
    seen = {}

    def fake_batch(param_list, *, n_seeds, jobs):
        seen["n"] = len(param_list)
        seen["n_seeds"] = n_seeds
        return [_fake_result(p, aor=20.0) for p in param_list]

    monkeypatch.setattr(runner, "evaluate_batch", fake_batch)
    X = screen.sample(8)
    results = screen.run_screen(X, n_seeds=2)
    assert seen == {"n": 8, "n_seeds": 2}
    assert len(results) == 8


def test_collect_marks_failed_candidate_nan():
    X = screen.sample(3)
    params = screen.rows_to_params(X)
    results = [
        _fake_result(params[0], aor=18.0),
        _fake_result(params[1], aor=None),   # all-seeds failure
        _fake_result(params[2], aor=29.0),
    ]
    df = screen.collect(X, results)
    assert len(df) == 3
    assert np.isnan(df.loc[1, "aor"]) and np.isnan(df.loc[1, "bulk_density"])
    assert df.loc[0, "aor"] == 18.0 and df.loc[2, "aor"] == 29.0
    assert set(["fric", "rollfric", "rest", "hash", "trial_dir"]).issubset(df.columns)


# ------------------------------------------------------------- analysis
def _synthetic_frame(n=60, seed=0):
    """AoR driven by fric and rollfric only; rest has no real effect."""
    X = screen.sample(n)
    rng = np.random.default_rng(seed)
    aor = 40.0 * X[:, 0] + 60.0 * X[:, 1] + rng.normal(0, 0.3, n)
    params = screen.rows_to_params(X)
    results = [_fake_result(p, aor=float(a)) for p, a in zip(params, aor)]
    return screen.collect(X, results)


def test_sensitivity_ranks_friction_above_restitution_and_freezes_rest():
    df = _synthetic_frame()
    sens = screen.analyze_sensitivity(df)
    assert sens["ranking"][-1] == "rest"                 # rest is least influential
    assert sens["delta"]["rest"] < sens["delta"]["fric"]
    assert sens["delta"]["rest"] < sens["delta"]["rollfric"]
    assert "rest" in sens["frozen"]
    assert "fric" not in sens["frozen"] and "rollfric" not in sens["frozen"]
    assert sens["n_used"] == len(df) and sens["n_dropped"] == 0


def test_sensitivity_drops_and_counts_nan_rows():
    df = _synthetic_frame(n=40)
    df.loc[[2, 7, 11], "aor"] = np.nan
    sens = screen.analyze_sensitivity(df)
    assert sens["n_dropped"] == 3
    assert sens["n_used"] == len(df) - 3


def test_bracketing_detects_reachable_target():
    df = _synthetic_frame()
    brk = screen.bracketing(df)
    assert brk["aor_min"] < screen.TARGET_AOR < brk["aor_max"]
    assert brk["target_bracketed"] is True
    assert brk["nearest"] is not None
    assert abs(brk["nearest"]["aor"] - screen.TARGET_AOR) <= 2.0


def test_bracketing_reports_unreachable_target():
    # all candidates well below the target band
    X = screen.sample(20)
    results = [_fake_result(p, aor=10.0) for p in screen.rows_to_params(X)]
    df = screen.collect(X, results)
    brk = screen.bracketing(df)
    assert brk["target_bracketed"] is False
