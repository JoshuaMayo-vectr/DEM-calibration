"""Phase-9 tests for the drum dynamic-AoR measurement in calibration/measure.py.

Synthetic drum beds of analytically known surface angle must measure within
±0.5° (the Phase-4 accuracy bar carried over), the central chord window must
survive S-shaped end deviations, and the steadiness / rotation-sign guards
must fire when they should.
"""

import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from calibration.measure import (  # noqa: E402
    measure_drum,
    measure_drum_frame,
    read_dump,
)
from tests import synth  # noqa: E402


def _frame_angle(df, **kw):
    return measure_drum_frame(df, **kw)["angle_deg"]


# ------------------------------------------------------ accuracy on synthetic
# A single frame of the thin (25 mm) drum slice carries ~±1° realization
# noise — only ~40 surface bins vs the heap's full azimuth. The pipeline never
# consumes a single frame: the strict ±0.5° Phase-4 accuracy bar applies to
# the multi-frame mean (test_multi_frame_mean_accuracy), single frames get a
# realistic unbiasedness + scatter check.

@pytest.mark.parametrize("true_angle", [15.0, 30.0, 36.17])
def test_drum_bed_angle(true_angle):
    rng = np.random.default_rng(42)
    df = synth.make_drum_bed(true_angle, rng)
    assert abs(_frame_angle(df) - true_angle) <= 1.5


def test_drum_bed_angle_sweep():
    """Single frames: unbiased (mean |err| small) with bounded scatter."""
    errors = []
    for angle in (15.0, 24.0, 30.0, 36.0):
        for seed in range(10):
            rng = np.random.default_rng(1000 + seed)
            df = synth.make_drum_bed(angle, rng)
            errors.append(_frame_angle(df) - angle)
    errors = np.array(errors)
    assert abs(errors.mean()) <= 0.25        # unbiased
    assert np.abs(errors).max() <= 1.5       # bounded single-frame scatter


def test_multi_frame_mean_accuracy():
    """The 19-frame mean (what the optimizer consumes) must hit ±0.5°."""
    for angle in (15.0, 30.0, 36.17):
        angs = [
            _frame_angle(synth.make_drum_bed(angle, np.random.default_rng(5000 + k)))
            for k in range(19)
        ]
        assert abs(float(np.mean(angs)) - angle) <= 0.5


def test_fill_fraction_independence():
    """Same surface angle at 30% vs 50% fill must read the same."""
    rng = np.random.default_rng(7)
    a30 = _frame_angle(synth.make_drum_bed(30.0, rng, fill_frac=0.3))
    a50 = _frame_angle(synth.make_drum_bed(30.0, rng, fill_frac=0.5))
    assert abs(a30 - 30.0) <= 0.7
    assert abs(a50 - 30.0) <= 0.7


def test_s_curve_robustness():
    """Cubic end-deviation (S-shaped surface) must not pull the central-window
    fit off by more than 0.7° — the kinks live outside the chord window."""
    rng = np.random.default_rng(11)
    df = synth.make_drum_bed(30.0, rng, s_amp=0.006)
    assert abs(_frame_angle(df) - 30.0) <= 0.7


def test_slope_sign_convention():
    """slope_sign=-1 beds carry dz/dx < 0; the frame fit keeps the sign."""
    rng = np.random.default_rng(3)
    f = measure_drum_frame(synth.make_drum_bed(25.0, rng, slope_sign=-1.0))
    assert f["slope"] < 0
    f = measure_drum_frame(synth.make_drum_bed(25.0, rng, slope_sign=+1.0))
    assert f["slope"] > 0


# --------------------------------------------------- multi-frame aggregation

def _frame_series(angles, tmp_path, slope_sign=-1.0):
    dfs = [synth.make_drum_bed(a, np.random.default_rng(100 + i),
                               slope_sign=slope_sign)
           for i, a in enumerate(angles)]
    steps = [425000 + 25000 * i for i in range(len(angles))]
    return synth.write_dump_series(dfs, tmp_path / "post", "tst", steps)


def test_measure_drum_averages(tmp_path):
    """Multi-frame mean lands on the common angle; frame std is reported."""
    paths = _frame_series([30.0] * 8, tmp_path)
    res = measure_drum(paths)
    assert abs(res["drum_aor_deg"] - 30.0) <= 0.5
    assert res["n_frames"] == 8
    assert res["drum_aor_frame_std"] < 1.0
    assert not any("not steady" in w for w in res["warnings"])


def test_steadiness_guard(tmp_path):
    """A drifting angle series must trigger the extend-SPINUP warning."""
    paths = _frame_series(list(np.linspace(24.0, 32.0, 8)), tmp_path)
    res = measure_drum(paths)
    assert any("not steady" in w for w in res["warnings"])
    assert abs(res["drum_trend_deg"]) > 1.0


def test_rotation_sign_guard(tmp_path):
    """Beds tilted the wrong way must trigger the rotation-direction warning."""
    paths = _frame_series([30.0] * 5, tmp_path, slope_sign=+1.0)
    res = measure_drum(paths)
    assert any("rotation" in w for w in res["warnings"])


def test_frames_sorted_by_step(tmp_path):
    """Frame order must follow the numeric step, not the lexical filename."""
    dfs = [synth.make_drum_bed(a, np.random.default_rng(i))
           for i, a in enumerate((20.0, 25.0, 30.0))]
    # lexically: 1000000 < 500000 < 75000 — numerically the reverse
    paths = synth.write_dump_series(dfs, tmp_path / "post", "tst",
                                    [75000, 500000, 1000000])
    res = measure_drum(paths[::-1])  # hand them over scrambled
    # drift must be computed on the numeric order: rising 20 -> 30
    assert res["drum_trend_deg"] > 0


def test_audit_plot_emitted(tmp_path):
    paths = _frame_series([30.0] * 5, tmp_path)
    out = tmp_path / "drum_fit.png"
    res = measure_drum(paths, plot_path=out)
    assert out.exists() and out.stat().st_size > 10_000
    assert res["plot_path"] == str(out)


def test_round_trip_through_dump(tmp_path):
    """write_dump_series -> read_dump preserves the measured angle."""
    rng = np.random.default_rng(5)
    df = synth.make_drum_bed(28.0, rng)
    [p] = synth.write_dump_series([df], tmp_path / "post", "tst", [425000])
    assert abs(_frame_angle(read_dump(p)) - 28.0) <= 0.6
