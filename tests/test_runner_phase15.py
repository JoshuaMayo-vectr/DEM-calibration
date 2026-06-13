"""Phase-15 tests: particle shape (multisphere) plumbing (no LIGGGHTS).

Two contracts mirror Phases 12–14:
1. DEFAULT NEUTRALITY — a wheat material spelling out the locked shape
   ('sphere') still canonicalizes to None, so the legacy cache namespace and
   the byte-identical static render are untouched (the pinned hash survives).
2. NAMESPACE ISOLATION — a multisphere clump gets its own hash, renders the
   particletemplate/multisphere line + the multisphere integrator + a `mol`
   dump column, and runs serial (-np 1); the 45° hold-out stays single-sphere
   (the fourth pin, alongside cohesion / wall friction / contact model).
"""

import math
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from calibration import runner  # noqa: E402

PARAMS = {"fric": 0.5, "rollfric": 0.12}
WHEAT = dict(runner.WHEAT_MATERIAL)
CLUMP = [[0.0, 0.0, -0.0026, 0.00175],
         [0.0, 0.0, 0.0, 0.00200],
         [0.0, 0.0, 0.0026, 0.00175]]
MULTI = {**WHEAT, "name": "wheat-prolate",
         "particle_shape": "multisphere", "clump_spheres": CLUMP}


# ------------------------------------------------------------- default neutrality
def test_default_shape_collapses_to_none():
    """Spelling out the locked particle_shape='sphere' is still the default."""
    assert runner.material_canon({**WHEAT, "particle_shape": "sphere"}) is None


def test_default_hash_unchanged_by_phase15():
    """The pinned wheat aor hash (100+ cached trials) survives the Phase-15
    additions — exactly because the default shape adds nothing to the hash."""
    assert runner.params_hash(PARAMS) == "a3338ce730"
    assert runner.params_hash(PARAMS, "aor",
                              {**WHEAT, "particle_shape": "sphere"}) == "a3338ce730"


def test_default_render_still_byte_identical():
    """All three default renders stay byte-for-byte the static .in files."""
    for resp in ("aor", "drum", "drum45"):
        static = runner.RESPONSES[resp]["template"].read_text()
        assert runner._render_text(resp, None) == static


# ------------------------------------------------------------- shape validation
@pytest.mark.parametrize("bad", [
    {"particle_shape": "polyhedron"},                       # unsupported
    {"particle_shape": "multisphere"},                      # missing clump_spheres
    {"particle_shape": "multisphere", "clump_spheres": [[0, 0, 0, 0.002]]},  # < 2
    {"particle_shape": "multisphere",
     "clump_spheres": [[0, 0, 0, 0.002], [0, 0, 0.003, 0.0]]},    # r <= 0
    {"particle_shape": "multisphere",
     "clump_spheres": [[0, 0, 0, 0.002], [0, 0, 0.003]]},         # not 4 numbers
])
def test_material_canon_rejects_bad_clump(bad):
    with pytest.raises(ValueError):
        runner.material_canon({**WHEAT, **bad})


# ------------------------------------------------------------- multisphere render
def test_multisphere_render_replaces_template_and_integrator():
    text = runner._render_text("aor", runner.material_canon(MULTI))
    assert "particletemplate/multisphere" in text
    assert "nspheres 3" in text
    assert "spheres 0 0 -0.0026 0.00175 0 0 0 0.002 0 0 0.0026 0.00175 type 1" in text
    assert "particledistribution/discrete 32452867 1 pts1 1.0" in text
    assert "fix\tintegr all multisphere" in text
    assert "fix\tintegr all nve/sphere" not in text            # dropped entirely
    assert "particletemplate/sphere" not in text               # PSD block replaced
    # body id added to BOTH the running dump and the final write_dump
    assert "id type mol x y z" in text
    assert text.count("id type mol x y z") == 2
    # the contact model is untouched by shape
    assert "pair_style gran model hertz tangential history rolling_friction epsd2" in text


def test_multisphere_gets_own_namespace():
    h0 = runner.params_hash(PARAMS, "aor", None)
    hm = runner.params_hash(PARAMS, "aor", MULTI)
    assert hm != h0
    assert hm != runner.params_hash(PARAMS, "aor",
                                    {**WHEAT, "name": "x", "particle_density_kgm3": 1300})


def test_drum45_holdout_pins_single_sphere():
    """The 45° hold-out renders single spheres even when the material is a
    multisphere clump — the fourth pin, alongside cohesion/wall/contact-model."""
    text = runner._render_text("drum45", runner.material_canon(MULTI))
    assert "fix\tintegr all nve/sphere" in text
    assert "particletemplate/multisphere" not in text
    assert "fix\tintegr all multisphere" not in text
    assert "id type mol" not in text


def test_drum_renders_single_sphere_heap_only_scope():
    """Multisphere is heap-only (Phase-14-style scope): the drum template has no
    multisphere block, so a multisphere material renders the single-sphere PSD."""
    text = runner._render_text("drum", runner.material_canon(MULTI))
    assert "particletemplate/multisphere" not in text
    assert "particletemplate/sphere" in text


# ------------------------------------------------------------- serial pin
def test_build_argv_uses_serial_ranks_for_multisphere(tmp_path):
    canon = runner.canonical(PARAMS)
    argv = runner._build_argv(canon, 1, tmp_path, "tag", "aor",
                              mat=runner.material_canon(MULTI))
    np_idx = argv.index("-np") + 1
    assert argv[np_idx] == "1"
    # a single-sphere custom material keeps the validated 2-rank launch
    sphere = runner.material_canon({**WHEAT, "name": "x", "particle_density_kgm3": 1300})
    argv2 = runner._build_argv(canon, 1, tmp_path, "tag", "aor", mat=sphere)
    assert argv2[argv2.index("-np") + 1] == str(runner.NRANKS)


# ------------------------------------------------------------- clump volume
def test_clump_equiv_volume_between_bounds():
    """The Monte-Carlo union volume is strictly below the naive sub-sphere sum
    (overlap is corrected) and at or above the largest single sub-sphere."""
    V = runner._clump_equiv_volume(CLUMP)
    v_max = (4 / 3) * math.pi * 0.00200**3
    v_sum = sum((4 / 3) * math.pi * r**3 for *_, r in CLUMP)
    assert v_max <= V < v_sum


def test_clump_equiv_volume_deterministic():
    """Fixed seed → a cached result and a recompute agree (cache stability)."""
    assert runner._clump_equiv_volume(CLUMP) == runner._clump_equiv_volume(CLUMP)
