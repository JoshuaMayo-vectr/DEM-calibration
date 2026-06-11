"""Phase-4 exit-criterion tests for calibration/measure.py.

Synthetic heaps of analytically known angle must measure within ±0.5°
(roadmap exit criterion 1), plus regression tests against the real
Phase-3 dumps: the toe-free fit must read at or above the crude baseline
(which under-reads by including the rounded toe) while preserving the
low < med < high friction ordering.
"""

import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from calibration.measure import (  # noqa: E402
    fit_flank,
    heap_profile,
    measure_angle,
    measure_bulk_density,
    measure_heap,
    read_dump,
)
from tests import synth  # noqa: E402

PHASE3 = REPO / "results" / "phase3-aor"


def _angle(df, **kw):
    return measure_angle(df, **kw)["angle_deg"]


# ----------------------------------------------------- exit criterion 1

@pytest.mark.parametrize("true_angle", [15.0, 25.0, 30.0])
def test_cone_angle(true_angle):
    rng = np.random.default_rng(42)
    df = synth.make_cone(true_angle, rng)
    assert abs(_angle(df) - true_angle) <= 0.5


def test_cone_angle_sweep():
    """Statistical accuracy across angles and seeds — guards against the
    single-seed tests passing by luck. Mean |error| must stay well inside
    the ±0.5° criterion; no single case may exceed twice it."""
    errs = []
    for angle in (12.0, 18.0, 25.0, 30.0):
        for seed in range(60, 70):
            df = synth.make_cone(angle, np.random.default_rng(seed))
            errs.append(_angle(df) - angle)
    errs = np.abs(errs)
    assert errs.mean() <= 0.35
    assert errs.max() <= 1.0


def test_truncated_cone():
    """Plateaued heaps (apex sliced at 70% height) must measure like full
    cones — the window top tracks the plateau, the bottom the true apex."""
    errs = []
    for seed in range(60, 70):
        df = synth.make_truncated_cone(25.0, np.random.default_rng(seed))
        errs.append(_angle(df) - 25.0)
    errs = np.abs(errs)
    assert errs.mean() <= 0.35
    assert errs.max() <= 0.75


def test_flat_disc():
    rng = np.random.default_rng(44)
    df = synth.make_flat_disc(rng)
    res = measure_angle(df)
    assert abs(res["angle_deg"]) < 2.0
    assert res["method"].startswith("radial_window_flat")


def test_outlier_robustness():
    rng = np.random.default_rng(45)
    df = synth.add_outliers(synth.make_cone(25.0, rng), rng, frac=0.01)
    assert abs(_angle(df) - 25.0) <= 0.5


def test_rounded_toe():
    rng = np.random.default_rng(46)
    df = synth.make_cone_with_toe(25.0, rng)
    res = measure_angle(df)
    assert abs(res["angle_deg"] - 25.0) <= 0.5
    # naive full-profile fit on the same data must under-read — this is
    # the documented flaw of the Phase-3 crude baseline
    profile = heap_profile(df)
    naive = fit_flank(profile, window=(0.0, 1.0), flat_height_diams=0.0)
    assert naive["angle_deg"] < res["angle_deg"]


# ----------------------------------------------------------- bulk density

def test_bulk_density_known_packing():
    rng = np.random.default_rng(47)
    phi = 0.56
    df = synth.make_packed_cylinder(phi, rng)
    res = measure_bulk_density(df)
    expected = phi * 1400.0
    assert abs(res["bulk_density_kgm3"] - expected) / expected <= 0.03


# ------------------------------------------------------ real-dump parsing

def test_read_dump_real():
    df = read_dump(PHASE3 / "high" / "post" / "high_final.liggghts")
    assert len(df) == 4000
    assert set(np.round(df["radius"].unique(), 5)) <= {0.0017, 0.00185, 0.002}
    assert {"x", "y", "z", "vx", "radius"}.issubset(df.columns)


def test_real_triplet_sane():
    angles = {
        tag: _angle(read_dump(PHASE3 / tag / "post" / f"{tag}_final.liggghts"))
        for tag in ("low", "med", "high")
    }
    assert angles["low"] < 3.0
    assert angles["low"] < angles["med"] < angles["high"]
    # toe-free fit must read at or above the crude baseline (18.4 / 26.1)
    assert angles["med"] >= 18.4
    assert angles["high"] >= 26.1


# --------------------------------------------------------- plot & sectors

def test_audit_plot_emitted(tmp_path):
    out = tmp_path / "audit.png"
    res = measure_heap(
        PHASE3 / "high" / "post" / "high_final.liggghts",
        settled_dump=PHASE3 / "high" / "post" / "high_50000.liggghts",
        plot_path=out,
    )
    assert out.exists() and out.stat().st_size > 0
    assert res["plot_path"] == str(out)
    assert res["bulk_density_kgm3"] is not None


def test_sector_std_reported():
    rng = np.random.default_rng(48)
    df = synth.make_cone(25.0, rng)
    res = measure_angle(df)
    assert res["sector_mean"] is not None
    assert res["sector_std"] is not None
    assert res["sector_std"] < 1.5  # ideal cone: quadrants agree closely
