"""Tests for the drawdown flow-rate measurement (Phase-9 probe)."""

import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from calibration.measure import measure_drawdown  # noqa: E402

DT = 8.0e-6


def _write_log(path: Path, steps, mass, *, extra_blocks: bool = True) -> Path:
    """Emit a LIGGGHTS-log-shaped file: indented 'Step ... ms[1] ...' header
    (the f_ prefix is stripped in real logs), data rows, surrounding noise."""
    lines = ["LIGGGHTS (Version LIGGGHTS-PUBLIC 3.8.0)",
             "variable FRIC index 0.40", "run 50000"]
    if extra_blocks:  # a settle-stage thermo block with zero mass
        lines.append("    Step    Atoms         KinEng          ms[1]          ts[1]          ts[2]")
        for s in range(0, 50001, 25000):
            lines.append(f"   {s}     4000   1e-05   0   0.07   0.02")
        lines.append("Loop time of 36.6 on 2 procs")
    lines.append("    Step    Atoms         KinEng          ms[1]          ts[1]          ts[2]")
    for s, m in zip(steps, mass):
        lines.append(f"   {s}     4000   1e-05   {m:.8g}   0.07   0.02")
    lines.append("Loop time of 93.9 on 2 procs")
    path.write_text("\n".join(lines))
    return path


def test_recovers_known_slope(tmp_path):
    rate = 0.047  # kg/s
    steps = np.arange(61250, 236250, 1000)
    t = steps * DT
    mass = np.clip(rate * (t - t[0]), 0, None)
    log = _write_log(tmp_path / "log.t", steps, mass)
    res = measure_drawdown(log)
    assert res["flow_rate_kgs"] == pytest.approx(rate, rel=0.02)
    assert res["fit_r2"] > 0.999
    assert not res["warnings"]


def test_window_excludes_transient_and_tail(tmp_path):
    """Slow start + saturated end must not bias the central-window slope."""
    rate = 0.060
    steps = np.arange(0, 200000, 1000)
    t = steps * DT
    m_lin = rate * (t - 0.2)
    mass = np.where(t < 0.2, 0.0, np.minimum(m_lin, 0.062))  # ramp then drain out
    log = _write_log(tmp_path / "log.t", steps, mass, extra_blocks=False)
    res = measure_drawdown(log)
    assert res["flow_rate_kgs"] == pytest.approx(rate, rel=0.05)


def test_no_flow_returns_zero(tmp_path):
    steps = np.arange(0, 100000, 1000)
    log = _write_log(tmp_path / "log.t", steps, np.zeros(len(steps)))
    res = measure_drawdown(log)
    assert res["flow_rate_kgs"] == 0.0
    assert any("no mass" in w for w in res["warnings"])


def test_unsteady_flow_warns(tmp_path):
    """Intermittent (arching) discharge must trip the steadiness warning."""
    rng = np.random.default_rng(3)
    steps = np.arange(0, 200000, 1000)
    t = steps * DT
    stick = (np.sin(t * 12.0) > 0).astype(float)  # stop-and-go flow
    mass = np.cumsum(0.05 * stick) * (t[1] - t[0]) + rng.normal(0, 1e-4, len(t))
    mass = np.maximum.accumulate(np.clip(mass, 0, None))
    log = _write_log(tmp_path / "log.t", steps, mass, extra_blocks=False)
    res = measure_drawdown(log)
    assert any("not steady" in w for w in res["warnings"])


def test_real_smoke_log_if_present():
    log = REPO / "results" / "phase9-drum" / "drawdown-smoke" / "log.dev"
    if not log.exists():
        pytest.skip("smoke log not present")
    res = measure_drawdown(log)
    assert 0.02 < res["flow_rate_kgs"] < 0.12   # plausible wheat orifice flow
    assert res["fit_r2"] > 0.99
