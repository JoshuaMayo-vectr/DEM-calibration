"""Phase-10 tests for the material card — schema validation, internal
consistency, and the reproduce contract (card-only inputs). No simulations:
runner.evaluate is stubbed."""

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from calibration import material_card, runner  # noqa: E402


def _minimal_card() -> dict:
    """A schema-complete card with the real shapes but synthetic numbers."""
    return {
        "name": "wheat-test", "material": "wheat (test)", "version": "1.0.0",
        "date": "2026-06-12",
        "engine": {"code": "LIGGGHTS-PUBLIC", "version": "3.8.0",
                   "build": "test"},
        "contact_model": {"pair_style": "gran model hertz tangential history "
                                        "rolling_friction epsd2",
                          "cohesion": "none", "particle_shape": "sphere"},
        "parameters": {
            "fric": {"value": 0.4001, "role": "calibrated"},
            "rollfric": {"value": 0.1374, "role": "calibrated"},
            "rest": {"value": 0.5762, "role": "calibrated-weak"},
        },
        "equivalence_family": {
            "constraint": "test", "caveat": "test",
            "anchors": [{"fric": 0.2477, "rollfric": 0.2249},
                        {"fric": 0.6000, "rollfric": 0.1203}],
        },
        "fixed_inputs": {
            "particle_density_kgm3": 1400,
            "psd_mm": {"diameters": [3.4, 3.7, 4.0],
                       "mass_weights": [0.25, 0.5, 0.25]},
            "youngs_modulus_pa": 1.0e7, "poisson_ratio": 0.25,
            "timestep_s": 8.0e-6,
            "wall_acrylic": {"fric": 0.36, "rollfric": 0.29, "source": "test"},
        },
        "responses": {
            "aor": {"value_deg": 26.39, "std_deg": 0.63, "n_seeds": 5,
                    "target_deg": 27.0, "target_sigma_deg": 1.5,
                    "protocol": "test"},
            "drum": {"value_deg": 38.06, "std_deg": 0.20, "n_seeds": 5,
                     "target_deg": 36.17, "target_sigma_deg": 3.1,
                     "protocol": "test"},
            "bulk_density": {"value": 781.7, "calibrated": False,
                             "literature": 780},
        },
        "validation": {
            "scenario": "drum45 hold-out", "measured_deg": 43.65,
            "sigma_deg": 2.92, "criterion": "<= 2 sigma", "prestated": True,
            "predicted_deg": 44.0, "predicted_std_deg": 0.3,
            "abs_error_deg": 0.35, "passed": True,
            "family_endpoints_discriminate": False,
            "deviations": ["test"], "verdict_file": "test",
        },
        "evidence": {"ground_truth": "test"},
        "reproduction": {"command": "test", "n_seeds": 5,
                         "tolerance": {"aor": 1.0, "drum": 1.0,
                                       "bulk_density": 25.0}},
        "scope": {"valid_for": ["test"], "not_calibrated_for": ["test"]},
    }


# ----------------------------------------------------------- validate-card

def test_minimal_card_is_valid():
    assert material_card.validate_card(_minimal_card()) == []


def test_missing_required_section_fails_schema():
    card = _minimal_card()
    del card["validation"]
    errors = material_card.validate_card(card)
    assert any("validation" in e for e in errors)


def test_unknown_top_level_key_fails_schema():
    card = _minimal_card()
    card["surprise"] = 1
    assert material_card.validate_card(card)


def test_point_outside_family_fails_consistency():
    card = _minimal_card()
    card["parameters"]["fric"]["value"] = 0.9
    errors = material_card.validate_card(card)
    assert any("outside family" in e for e in errors)


def test_tolerance_without_response_fails_consistency():
    card = _minimal_card()
    card["reproduction"]["tolerance"]["drawdown"] = 2.0
    errors = material_card.validate_card(card)
    assert any("drawdown" in e for e in errors)


# -------------------------------------------------------------- reproduce

def _stub_evaluate(aor=26.39, density=781.7, drum=38.06, calls=None):
    def stub(params, *, n_seeds=2, jobs=None, force=False, response="aor"):
        if calls is not None:
            calls.append((response, dict(params), n_seeds))
        if response == "aor":
            return {"aor": aor, "bulk_density": density, "aor_std": 0.5,
                    "n_ok": n_seeds}
        return {"drum_aor": drum, "drum_aor_std": 0.2,
                "drum_frame_std": 0.9, "n_ok": n_seeds}
    return stub


def test_reproduce_passes_on_matching_replay(monkeypatch):
    calls = []
    monkeypatch.setattr(runner, "evaluate", _stub_evaluate(calls=calls))
    report = material_card.reproduce(_minimal_card())
    assert report["ok"] is True
    assert {c["response"] for c in report["checks"]} == \
        {"aor", "bulk_density", "drum"}
    # the "only the card" contract: evaluate received exactly the card's
    # parameter values (+ the card's wall pair for the drum), 5 seeds
    aor_call = next(c for c in calls if c[0] == "aor")
    assert aor_call[1] == {"fric": 0.4001, "rollfric": 0.1374, "rest": 0.5762}
    assert aor_call[2] == 5
    drum_call = next(c for c in calls if c[0] == "drum")
    assert drum_call[1] == {"fric": 0.4001, "rollfric": 0.1374,
                            "rest": 0.5762, "capfric": 0.36, "caproll": 0.29}


def test_reproduce_fails_outside_tolerance(monkeypatch):
    monkeypatch.setattr(runner, "evaluate", _stub_evaluate(aor=28.0))
    report = material_card.reproduce(_minimal_card())   # |28-26.39| > 1.0
    assert report["ok"] is False
    bad = next(c for c in report["checks"] if c["response"] == "aor")
    assert bad["ok"] is False


def test_reproduce_fails_on_dead_response(monkeypatch):
    monkeypatch.setattr(runner, "evaluate", _stub_evaluate(drum=None))
    report = material_card.reproduce(_minimal_card())
    assert report["ok"] is False
