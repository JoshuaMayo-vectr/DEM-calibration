"""Tests for the Phase-8.5 material layer in calibration/runner.py.

The two load-bearing contracts:
1. DEFAULT NEUTRALITY — the wheat default must change nothing: same hashes
   (the existing results/cache/ stays valid), same static template, same argv.
2. NAMESPACE ISOLATION — any non-default material gets its own hash, its own
   rendered template, DT-consistent stage boundaries, and a scaled wall limit.
No LIGGGHTS: the engine is stubbed where a launch would happen.
"""

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from calibration import runner  # noqa: E402

PARAMS = {"fric": 0.5, "rollfric": 0.12}
MAIZE = {"name": "maize", "particle_density_kgm3": 1250.0,
         "psd_mm": [[6.0, 0.3], [7.0, 0.5], [8.0, 0.2]],
         "youngs_modulus_pa": 1.0e7, "timestep_s": None, "n_particles": 1200}


# ------------------------------------------------------------- canonicalization
def test_material_canon_none_and_default_equivalent():
    assert runner.material_canon(None) is None
    assert runner.material_canon(dict(runner.WHEAT_MATERIAL)) is None
    # spelling out the wheat values explicitly is still the default
    assert runner.material_canon({
        "name": "renamed but physically wheat",
        "particle_density_kgm3": 1400, "psd_mm": [[3.4, 0.25], [3.7, 0.5], [4.0, 0.25]],
        "youngs_modulus_pa": 1e7, "timestep_s": 8e-6, "n_particles": 4000}) is None


def test_material_canon_normalizes():
    mat = runner.material_canon({"psd_mm": [[8.0, 2.0], [6.0, 3.0], [7.0, 5.0]],
                                 "particle_density_kgm3": 1250})
    assert [d for d, _ in mat["psd_mm"]] == [6.0, 7.0, 8.0]      # sorted
    assert sum(w for _, w in mat["psd_mm"]) == pytest.approx(1.0)  # normalized
    assert mat["dt"] > runner.DT_WHEAT                            # bigger grains
    assert mat["npart"] == 4000                                   # default filled


def test_material_canon_accepts_its_own_output():
    mat = runner.material_canon(MAIZE)
    assert runner.material_canon(mat) == mat                      # idempotent


@pytest.mark.parametrize("bad", [
    {"psd_mm": [[0.1, 1.0]]},                                    # diameter too small
    {"psd_mm": [[3.4, -0.2], [4.0, 1.2]]},                       # negative fraction
    {"psd_mm": [[d, 0.1] for d in range(1, 11)]},                # too many bins
    {"particle_density_kgm3": 5},                                # implausible rho
    {"youngs_modulus_pa": 1e12},                                 # outside softened range
    {"n_particles": 10},                                         # too few
    {"timestep_s": 1.0},                                         # absurd dt
])
def test_material_canon_rejects(bad):
    with pytest.raises(ValueError):
        runner.material_canon({**MAIZE, **bad})


# ------------------------------------------------------------- hash contracts
def test_default_hash_pinned_to_existing_cache():
    """THE back-compat regression: the wheat default must reproduce the exact
    legacy hash (this one has 100+ cached trials behind it)."""
    assert runner.params_hash(PARAMS) == "a3338ce730"
    assert runner.params_hash(PARAMS, "aor", None) == "a3338ce730"
    assert runner.params_hash(PARAMS, "aor", runner.WHEAT_MATERIAL) == "a3338ce730"


def test_custom_material_gets_own_namespace():
    h_default = runner.params_hash(PARAMS)
    h_custom = runner.params_hash(PARAMS, "aor", MAIZE)
    assert h_custom != h_default
    # name is cosmetic — must NOT split the namespace
    assert runner.params_hash(PARAMS, "aor", {**MAIZE, "name": "other"}) == h_custom
    # but physics does
    assert runner.params_hash(PARAMS, "aor",
                              {**MAIZE, "particle_density_kgm3": 1300}) != h_custom


def test_trial_dir_and_tag_follow_material():
    d0 = runner.trial_dir(PARAMS, 1, "aor")
    d1 = runner.trial_dir(PARAMS, 1, "aor", MAIZE)
    assert d0 != d1
    assert runner._tag(PARAMS, 1, "aor", MAIZE) != runner._tag(PARAMS, 1, "aor")


# ------------------------------------------------------------- template render
@pytest.mark.parametrize("response", ["aor", "drum", "drum45"])
def test_default_render_is_byte_identical(response):
    """The .j2 variant rendered with wheat defaults == the static .in file —
    the contract that lets the default path keep using the static template."""
    static = runner.RESPONSES[response]["template"].read_text()
    assert runner._render_text(response, None) == static


def test_custom_render_substitutes_material():
    mat = runner.material_canon(MAIZE)
    text = runner._render_text("aor", mat)
    assert "radius constant 0.003\n" in text or "radius constant 0.003 " not in text
    assert "radius constant 0.0035" in text and "radius constant 0.004" in text
    assert "variable RHO        equal 1250" in text
    assert "variable NPART      index 1200" in text
    assert f"particledistribution/discrete {runner.PSD_DIST_SEED} 3" in text
    # seeds distinct and from the verified prime list
    import re
    seeds = [int(s) for s in re.findall(r"particletemplate/sphere (\d+)", text)]
    assert len(set(seeds)) == len(seeds)
    assert all(s in runner.PSD_SEEDS for s in seeds)


def test_custom_render_eight_bins():
    mat = runner.material_canon({"psd_mm": [[1 + 0.5 * i, 1.0] for i in range(8)]})
    text = runner._render_text("aor", mat)
    assert f"particledistribution/discrete {runner.PSD_DIST_SEED} 8" in text
    assert "pts8" in text


# ------------------------------------------------------------- derived physics
def test_dt_auto_anchored_to_wheat():
    assert runner.dt_auto(runner.WHEAT_MATERIAL["psd_mm"], 1400.0, 1e7) == \
        pytest.approx(runner.DT_WHEAT)
    # smaller grains -> smaller dt; softer -> bigger dt
    assert runner.dt_auto([[1.7, 1.0]], 1400.0, 1e7) < runner.DT_WHEAT
    assert runner.dt_auto(runner.WHEAT_MATERIAL["psd_mm"], 1400.0, 1e6) > runner.DT_WHEAT


def test_npart_scaling_keeps_drum_fill():
    mat = runner.material_canon(MAIZE)
    assert runner._npart_for("aor", mat) == 1200                  # user's choice
    drum_n = runner._npart_for("drum", mat)
    assert 400 < drum_n < 1200       # ~6.8x particle volume -> ~4600/6.8
    # drum fill is protocol-bound: heap count must NOT change it
    mat2 = runner.material_canon({**MAIZE, "n_particles": 2400})
    assert runner._npart_for("drum", mat2) == drum_n


def test_stage_boundaries_follow_dt():
    assert runner._steady_step_for("drum", None) == 475000
    assert runner._settle_step_for(None) == 50000
    mat = runner.material_canon({**MAIZE, "timestep_s": 4e-6})
    assert runner._steady_step_for("drum", mat) == 950000         # (0.8+3.0)/4e-6
    assert runner._steady_step_for("drum45", mat) == 1950000      # (0.8+7.0)/4e-6
    assert runner._settle_step_for(mat) == 100000   # ceil(0.4/4e-6) on the dump grid
    assert runner._steady_step_for("aor", mat) is None


def test_heap_capacity():
    assert runner.heap_capacity(None) >= 4000              # wheat fits its default
    assert runner.heap_capacity(MAIZE) < 1200              # 6-8 mm grains don't fit 1200
    assert runner.heap_capacity(MAIZE) > 100


def test_wall_limit_scales_up_only():
    assert runner._scaled_wall_limit("aor", None) == 600
    cheap = runner.material_canon(MAIZE)                          # fewer, bigger
    assert runner._scaled_wall_limit("aor", cheap) == 600
    costly = runner.material_canon({**MAIZE, "psd_mm": [[1.0, 1.0]],
                                    "n_particles": 8000})
    assert runner._scaled_wall_limit("aor", costly) > 600
    assert runner._scaled_wall_limit("drum45", costly) <= 6 * 3600


# ------------------------------------------------------------- pipeline wiring
def test_simulate_renders_template_for_custom_material(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "CACHE", tmp_path / "cache")
    seen = {}

    def fake_launch(canon, seed, trial, tag, response="aor", *,
                    template=None, wall_limit=None):
        seen.update(template=template, wall_limit=wall_limit, trial=trial)

    monkeypatch.setattr(runner, "_launch_sim", fake_launch)
    mat = runner.material_canon(MAIZE)

    sim = runner._simulate(runner.canonical(PARAMS), 1, force=False,
                           response="aor", mat=mat)
    assert sim["status"] == "ran"
    assert seen["template"] is not None and seen["template"].exists()
    assert seen["template"].parent == seen["trial"]               # lives in the trial dir
    assert "variable RHO        equal 1250" in seen["template"].read_text()

    seen.clear()
    sim = runner._simulate(runner.canonical(PARAMS), 1, force=False,
                           response="aor", mat=None)
    assert sim["status"] == "ran" and seen["template"] is None    # default = static


def test_measured_json_carries_material(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "CACHE", tmp_path / "cache")
    mat = runner.material_canon(MAIZE)
    trial = tmp_path / "cache" / "x" / "seed1"
    (trial / "post").mkdir(parents=True)
    sim = {"status": "failed", "seed": 1, "trial": trial, "tag": "t",
           "error": "stub"}
    runner._finish(runner.canonical(PARAMS), sim, "aor", mat)
    data = json.loads((trial / "measured.json").read_text())
    assert data["material"]["name"] == "maize"                    # re-sim provenance
