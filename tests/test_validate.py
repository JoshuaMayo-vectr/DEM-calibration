"""Phase-10 tests for calibration/validate.py — verdict logic and the
pre-registration gate. No simulations: verdicts run on synthetic frames."""

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from calibration import validate  # noqa: E402

ACC = {
    "scenario": "test",
    "target_deg": 43.65,
    "sigma_deg": 2.92,
    "multiple": 2.0,
    "criterion": "test criterion",
}


def _df(rep_aor=44.0, rep_std=0.3, rep_n_ok=5, rep_drift=0,
        end_aors=(43.8, 44.2), end_std=0.3):
    rows = [{
        "fric": 0.4001, "rollfric": 0.1374, "rest": 0.5762,
        "role": "representative", "n_seeds": 5,
        "drum45_aor": rep_aor, "drum45_aor_std": rep_std,
        "drum45_frame_std": 0.9, "n_ok": rep_n_ok,
        "n_drift_warnings": rep_drift, "trial": "/tmp/x",
    }]
    for (f, r), a in zip(((0.2477, 0.2249), (0.6, 0.1203)), end_aors):
        rows.append({
            "fric": f, "rollfric": r, "rest": 0.5, "role": "endpoint",
            "n_seeds": 2, "drum45_aor": a, "drum45_aor_std": end_std,
            "drum45_frame_std": 0.9, "n_ok": 2, "n_drift_warnings": 0,
            "trial": "/tmp/x",
        })
    return pd.DataFrame(rows)


def test_verdict_pass_within_tolerance():
    v = validate.verdict(_df(rep_aor=44.0), ACC)
    assert v["passed"] is True
    assert abs(v["representative"]["abs_error_deg"] - 0.35) < 1e-9
    assert v["tolerance_deg"] == pytest.approx(5.84)
    # tight family span vs noise: no discrimination claim
    assert v["endpoints_discriminate"] is False


def test_verdict_fail_outside_tolerance():
    v = validate.verdict(_df(rep_aor=50.0), ACC)   # err 6.35 > 5.84
    assert v["passed"] is False


def test_verdict_fail_on_drift_warning():
    v = validate.verdict(_df(rep_aor=44.0, rep_drift=1), ACC)
    assert v["passed"] is False


def test_verdict_fail_on_too_few_seeds():
    v = validate.verdict(_df(rep_aor=44.0, rep_n_ok=3), ACC)
    assert v["passed"] is False


def test_verdict_detects_endpoint_separation():
    v = validate.verdict(_df(rep_aor=44.0, end_aors=(40.0, 48.0),
                             end_std=0.3), ACC)
    assert v["endpoints_discriminate"] is True
    assert v["family_span_deg"] == pytest.approx(8.0)


def test_verdict_per_anchor_in_band_flags():
    v = validate.verdict(_df(rep_aor=44.0, end_aors=(40.0, 55.0)), ACC)
    flags = {(a["role"], a["predicted_deg"]): a["in_band"]
             for a in v["per_anchor"]}
    assert flags[("representative", 44.0)] is True
    assert flags[("endpoint", 40.0)] is True     # |40-43.65| = 3.65 <= 5.84
    assert flags[("endpoint", 55.0)] is False


@pytest.fixture
def paths_to_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(validate, "OUTDIR", tmp_path)
    monkeypatch.setattr(validate, "ACCEPTANCE", tmp_path / "acceptance.json")
    monkeypatch.setattr(validate, "CSV", tmp_path / "validation.csv")
    monkeypatch.setattr(validate, "PLOT", tmp_path / "validation.png")
    monkeypatch.setattr(validate, "SHEET", tmp_path / "sheet.png")
    monkeypatch.setattr(validate, "VERDICT", tmp_path / "verdict.json")


def test_prestate_writes_and_refuses_overwrite(paths_to_tmp):
    acc = validate.prestate()
    assert validate.ACCEPTANCE.exists()
    assert acc["target_deg"] == 43.65 and acc["multiple"] == 2.0
    with pytest.raises(SystemExit):
        validate.prestate()
    validate.prestate(force=True)   # deliberate restatement allowed


def test_run_refuses_without_prestate(paths_to_tmp, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["validate.py", "run"])
    with pytest.raises(SystemExit, match="pre-registered"):
        validate.main()


def test_report_round_trip_from_csv(paths_to_tmp, monkeypatch):
    """report re-verdicts from CSV without touching the runner."""
    validate.prestate()
    _df(rep_aor=44.0).to_csv(validate.CSV, index=False)
    monkeypatch.setattr(sys, "argv", ["validate.py", "report"])
    validate.main()
    v = json.loads(validate.VERDICT.read_text())
    assert v["passed"] is True
    assert validate.PLOT.exists()
