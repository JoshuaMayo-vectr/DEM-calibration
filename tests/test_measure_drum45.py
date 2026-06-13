"""Phase-10 tests for the cover-slab (y_slab) drum measurement at 45 deg.

The published 45-deg measurement digitizes the surface trace adjacent to
the material side (the -y cover the bed leans on). These tests verify the
slab fit recovers that trace on leaning synthetic beds, that it isolates
the slab from a different surface elsewhere in the drum, and that the
sparse-slab and wrong-lean guards fire.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from calibration import measure  # noqa: E402
from tests import synth  # noqa: E402

SLAB = measure.DRUM45_Y_SLAB
LENGTH = 0.025


def test_slab_fit_recovers_cover_trace_on_leaning_bed():
    """axial_slope < 0 leans the bed on the -y cover while the x-z trace AT
    the cover keeps exactly angle_deg — the slab fit must read it."""
    rng = np.random.default_rng(42)
    errs = []
    for true_angle in (38.0, 43.0, 48.0):
        bed = synth.make_drum_bed(true_angle, rng, axial_slope=-0.8)
        f = measure.measure_drum_frame(bed, y_slab=SLAB)
        errs.append(abs(f["angle_deg"] - true_angle))
    assert max(errs) < 1.5, f"slab-fit errors {errs}"


def test_slab_fit_isolates_slab_from_rest_of_drum():
    """Compose a 43-deg surface inside the slab with a HIGHER, shallower
    25-deg surface elsewhere: the slab fit must read the slab, while a
    whole-bed fit (max statistic) is captured by the higher foreign
    surface — proving the slab filter is load-bearing."""
    rng = np.random.default_rng(7)
    r = synth.PARTICLE_R
    slab_bed = synth.make_drum_bed(43.0, rng, y_range=(-(LENGTH / 2 - r),
                                                       SLAB[1]))
    rest_bed = synth.make_drum_bed(25.0, rng, fill_frac=0.62,
                                   y_range=(SLAB[1], LENGTH / 2 - r))
    bed = pd.concat([slab_bed, rest_bed], ignore_index=True)

    slab_fit = measure.measure_drum_frame(bed, y_slab=SLAB)
    whole_fit = measure.measure_drum_frame(bed)
    assert abs(slab_fit["angle_deg"] - 43.0) < 1.5
    assert abs(whole_fit["angle_deg"] - 43.0) > 5.0   # smeared by the rest


def test_sparse_slab_warns_but_still_fits():
    rng = np.random.default_rng(3)
    bed = synth.make_drum_bed(40.0, rng)
    in_slab = (bed["y"] >= SLAB[0]) & (bed["y"] <= SLAB[1])
    # keep ~10% of slab particles: below the 300 warning threshold but
    # enough bins for a fit
    drop = in_slab & (rng.uniform(size=len(bed)) > 0.10)
    sparse = bed[~drop].reset_index(drop=True)
    f = measure.measure_drum_frame(sparse, y_slab=SLAB)
    assert any("slab" in w for w in f["warnings"])
    assert f["angle_deg"] > 0


def _write_frames(bed_factory, tmp_path, n_frames=5):
    frames = [bed_factory(i) for i in range(n_frames)]
    return synth.write_dump_series(frames, tmp_path / "post", "t",
                                   [475000 + 25000 * i for i in range(n_frames)])


def test_lean_guard_fires_on_wrong_tilt_sign(tmp_path):
    """Bed leaning on the +y cover (axial_slope > 0) while measuring the -y
    slab — the wrong-tilt-sign failure the guard exists for."""
    rng = np.random.default_rng(11)
    paths = _write_frames(
        lambda i: synth.make_drum_bed(40.0, rng, axial_slope=+0.8),
        tmp_path)
    res = measure.measure_drum(paths, y_slab=SLAB)
    assert any("not leaning" in w for w in res["warnings"])


def test_lean_guard_silent_on_correct_lean(tmp_path):
    rng = np.random.default_rng(12)
    paths = _write_frames(
        lambda i: synth.make_drum_bed(43.0, rng, axial_slope=-0.8),
        tmp_path)
    res = measure.measure_drum(paths, y_slab=SLAB)
    assert not any("not leaning" in w for w in res["warnings"])
    assert abs(res["drum_aor_deg"] - 43.0) < 1.5


def test_no_slab_behavior_unchanged(tmp_path):
    """Without y_slab the measurement is the Phase-9 path: no lean guard,
    whole-bed fit (regression for the vertical drum response)."""
    rng = np.random.default_rng(13)
    paths = _write_frames(lambda i: synth.make_drum_bed(30.0, rng), tmp_path)
    res = measure.measure_drum(paths)
    assert abs(res["drum_aor_deg"] - 30.0) < 1.5
    assert not any("leaning" in w for w in res["warnings"])


def test_axial_slope_zero_reproduces_legacy_generator():
    """axial_slope=0 must walk the original RNG path bit-for-bit — the
    Phase-9 drum tests depend on the generator's exact output."""
    a = synth.make_drum_bed(30.0, np.random.default_rng(99))
    b = synth.make_drum_bed(30.0, np.random.default_rng(99), axial_slope=0.0)
    pd.testing.assert_frame_equal(a, b)


def test_plot_target_band_parameterized(tmp_path):
    """The audit plot accepts the 45-deg target band (smoke: file written)."""
    rng = np.random.default_rng(21)
    paths = _write_frames(
        lambda i: synth.make_drum_bed(43.0, rng, axial_slope=-0.8),
        tmp_path)
    out = tmp_path / "drum_fit.png"
    res = measure.measure_drum(paths, y_slab=SLAB, plot_path=out,
                               target=measure.DRUM45_TARGET_DEG,
                               target_sigma=measure.DRUM45_TARGET_SIGMA)
    assert out.exists()
    assert res["plot_path"] == str(out)
