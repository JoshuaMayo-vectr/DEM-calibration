"""Phase-14 tests: configurable contact model + heap geometry (no LIGGGHTS).

Two contracts mirror Phases 12–13:
1. DEFAULT NEUTRALITY — a wheat material spelling out the locked contact model
   (hertz/epsd2) and geometry (R 0.040/H 0.100) still canonicalizes to None, so
   the legacy cache namespace and byte-identical static render are untouched.
2. NAMESPACE ISOLATION — a non-epsd2 rolling model, a hooke normal model, or a
   non-default cylinder each gets its own hash, the right model string / fixes,
   and (for geometry) a generated mesh; the 45° hold-out stays double-pinned.
"""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from calibration import runner  # noqa: E402

PARAMS = {"fric": 0.5, "rollfric": 0.12}
WHEAT = dict(runner.WHEAT_MATERIAL)
EPSD = {**WHEAT, "name": "wheat-epsd", "rolling_model": "epsd"}
HOOKE = {**WHEAT, "name": "wheat-hooke", "normal_model": "hooke"}
BIG = {**WHEAT, "name": "big-rig", "cyl_radius_m": 0.060, "cyl_height_m": 0.140}


# ------------------------------------------------------------- default neutrality
def test_default_models_and_geometry_collapse_to_none():
    """Spelling out the locked contact model + geometry is still the default."""
    assert runner.material_canon({
        **WHEAT, "normal_model": "hertz", "rolling_model": "epsd2",
        "cyl_radius_m": 0.040, "cyl_height_m": 0.100}) is None


def test_default_hash_unchanged_by_phase14():
    """The pinned wheat aor hash (100+ cached trials) survives the Phase-14
    additions — exactly because the default model/geometry add nothing."""
    assert runner.params_hash(PARAMS) == "a3338ce730"
    assert runner.params_hash(PARAMS, "aor", {
        **WHEAT, "normal_model": "hertz", "rolling_model": "epsd2",
        "cyl_radius_m": 0.040, "cyl_height_m": 0.100}) == "a3338ce730"


# ------------------------------------------------------------- model validation
@pytest.mark.parametrize("bad", [
    {"normal_model": "hooke3"},
    {"rolling_model": "epsd9"},
    {"cyl_radius_m": 0.5},        # outside 0.02–0.10
    {"cyl_height_m": 0.01},       # outside 0.05–0.20
])
def test_material_canon_rejects_phase14(bad):
    with pytest.raises(ValueError):
        runner.material_canon({**WHEAT, **bad})


# ------------------------------------------------------------- contact-model render
def test_epsd_render_adds_viscous_damping_fix_and_model_string():
    mat = runner.material_canon(EPSD)
    text = runner._render_text("aor", mat)
    assert "rolling_friction epsd\n" in text          # not epsd2
    assert "model hertz tangential history rolling_friction epsd" in text
    assert "coefficientRollingViscousDamping peratomtypepair 2 ${ROLLVISC}" in text
    assert "variable ROLLVISC" in text
    assert "characteristicVelocity" not in text       # hertz, not hooke


def test_hooke_render_adds_characteristic_velocity():
    mat = runner.material_canon(HOOKE)
    text = runner._render_text("aor", mat)
    assert "pair_style gran model hooke tangential history rolling_friction epsd2" in text
    assert "characteristicVelocity scalar ${CHARVEL}" in text
    assert "variable CHARVEL" in text


def test_epsd2_default_render_emits_no_extra_fixes():
    mat = runner.material_canon({**WHEAT, "name": "wheat-renamed"})  # default model
    # a renamed-but-physically-wheat material is None; force a real custom one
    mat = runner.material_canon({**WHEAT, "name": "x", "particle_density_kgm3": 1300})
    text = runner._render_text("aor", mat)
    assert "coefficientRollingViscousDamping" not in text
    assert "characteristicVelocity" not in text
    assert "rolling_friction epsd2" in text


def test_drum45_holdout_pins_hertz_epsd2_against_custom_model():
    """The 45° hold-out must render hertz/epsd2 even when the material is
    epsd/hooke — the same double-pin as cohesion and wall friction."""
    mat = runner.material_canon({**EPSD, "normal_model": "hooke"})
    text = runner._render_text("drum45", mat)
    assert "pair_style gran model hertz tangential history rolling_friction epsd2" in text
    assert "coefficientRollingViscousDamping" not in text
    assert "characteristicVelocity" not in text


# ------------------------------------------------------------- canonical rollvisc
def test_rollvisc_opt_in_only_when_positive():
    assert "rollvisc" not in runner.canonical(PARAMS)
    assert "rollvisc" not in runner.canonical({**PARAMS, "rollvisc": 0.0})
    assert runner.canonical({**PARAMS, "rollvisc": 0.1})["rollvisc"] == 0.1
    # opt-in means the hash is unchanged when absent
    assert runner.params_hash({**PARAMS, "rollvisc": 0.0}) == runner.params_hash(PARAMS)


def test_rollvisc_dropped_for_drum45_holdout():
    c = runner.canonical({**PARAMS, "rollvisc": 0.2, "rest": 0.5}, "drum45")
    assert "rollvisc" not in c


def test_model_change_gets_own_namespace():
    h0 = runner.params_hash(PARAMS, "aor", None)
    assert runner.params_hash(PARAMS, "aor", EPSD) != h0
    assert runner.params_hash(PARAMS, "aor", HOOKE) != h0
    assert runner.params_hash(PARAMS, "aor", EPSD) != runner.params_hash(PARAMS, "aor", HOOKE)


# ------------------------------------------------------------- geometry
def test_custom_geometry_gets_own_namespace_and_scales_regions():
    mat = runner.material_canon(BIG)
    assert runner.params_hash(PARAMS, "aor", BIG) != runner.params_hash(PARAMS)
    text = runner._render_text("aor", mat)
    # insert radius = cyl_radius - 0.0025, insert ztop = cyl_height - 0.015
    assert "cylinder z 0. 0. 0.0575 0.003 0.125" in text
    # safety box/walls scale outward
    assert "reg block -0.16 0.16 -0.16 0.16 0. 0.28" in text
    assert "xplane -0.15" in text


def test_default_geometry_custom_material_keeps_legacy_region_literals():
    """A default-geometry custom material (e.g. only density changed) must still
    render the exact historical region lines (no '0.2' vs '0.20' drift)."""
    mat = runner.material_canon({**WHEAT, "name": "x", "particle_density_kgm3": 1300})
    text = runner._render_text("aor", mat)
    assert "region\t\treg block -0.14 0.14 -0.14 0.14 0. 0.20 units box" in text
    assert "region\tbc cylinder z 0. 0. 0.0375 0.003 0.085 units box" in text
    assert "xplane -0.13" in text


def test_mesh_for_generates_custom_cylinder(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "MESH_CACHE", tmp_path / "meshes")
    mat = runner.material_canon(BIG)
    p = runner._mesh_for("aor", mat)
    assert p.exists() and p.parent == tmp_path / "meshes"
    assert "cylinder_r0.06_h0.14" in p.name
    txt = p.read_text()
    assert txt.startswith("solid cylinder") and "facet normal" in txt
    # default geometry / None falls back to the static registry mesh
    assert runner._mesh_for("aor", None) == runner.RESPONSES["aor"]["mesh"]
    assert runner._mesh_for("aor", runner.material_canon({**WHEAT, "name": "x",
            "particle_density_kgm3": 1300})) == runner.RESPONSES["aor"]["mesh"]
    # drum geometry is deferred — always the static mesh
    assert runner._mesh_for("drum", mat) == runner.RESPONSES["drum"]["mesh"]


def test_build_argv_passes_rollvisc_and_custom_mesh(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "MESH_CACHE", tmp_path / "meshes")
    mat = runner.material_canon(BIG)
    canon = runner.canonical({**PARAMS, "rollvisc": 0.15, "rest": 0.5})
    argv = runner._build_argv(canon, 1, tmp_path, "tag", "aor", mat=mat)
    assert "ROLLVISC" in argv and "0.15" in argv
    mesh_idx = argv.index("MESH") + 1
    assert "cylinder_r0.06_h0.14" in argv[mesh_idx]
