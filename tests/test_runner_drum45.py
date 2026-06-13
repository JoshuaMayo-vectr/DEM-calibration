"""Phase-10 tests for the drum45 (45-deg inclined drum) response — no LIGGGHTS.

Contracts under test: (1) the shell friction is a FIXED protocol input
(wheat-acrylic 0.36/0.29), NOT mirrored from the calibrated fric — the
property that makes the hold-out a genuine test of the particle-particle
set; (2) drum45 caches/hashes separately from drum and aor, and the legacy
drum hash is unchanged by the registry addition; (3) the stubbed engine
round-trips through slab measurement, pruning, side-view rendering, and the
cache.
"""

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from calibration import runner  # noqa: E402
from tests import synth  # noqa: E402

STEADY45 = runner.RESPONSES["drum45"]["steady_step"]


# -------------------------------------------------- canonical: fixed shell

def test_drum45_shell_friction_fixed_not_mirrored():
    c = runner.canonical({"fric": 0.5, "rollfric": 0.1}, "drum45")
    assert c["fricpw"] == 0.36 and c["rollfricpw"] == 0.29
    # the vertical drum mirrors — the difference IS the hold-out design
    d = runner.canonical({"fric": 0.5, "rollfric": 0.1}, "drum")
    assert d["fricpw"] == 0.5 and d["rollfricpw"] == 0.1


def test_drum45_canonical_has_tilt_and_protocol_knobs_not_lifth():
    c = runner.canonical({"fric": 0.5, "rollfric": 0.1}, "drum45")
    assert c["tilt"] == 45.0
    assert c["rotper"] == 12.0 and c["capfric"] == 0.36 and c["caproll"] == 0.29
    assert "lifth" not in c


def test_drum45_shell_override_respected_and_hash_relevant():
    c = runner.canonical({"fric": 0.5, "rollfric": 0.1, "fricpw": 0.5,
                          "rollfricpw": 0.1}, "drum45")
    assert c["fricpw"] == 0.5 and c["rollfricpw"] == 0.1
    assert runner.params_hash({"fric": 0.5, "rollfric": 0.1}, "drum45") != \
        runner.params_hash({"fric": 0.5, "rollfric": 0.1, "fricpw": 0.5},
                           "drum45")


def test_drum45_tilt_hash_relevant():
    assert runner.params_hash({"fric": 0.5, "rollfric": 0.1}, "drum45") != \
        runner.params_hash({"fric": 0.5, "rollfric": 0.1, "tilt": 30.0},
                           "drum45")


# ------------------------------------------------- cache layout / legacy pin

def test_drum_hash_pinned_unchanged_by_drum45():
    """The Phase-9 drum cache contract: adding drum45 must not move the drum
    canonical (no tilt key, mirrored fricpw)."""
    legacy_canon = {
        "fric": 0.5, "fricpw": 0.5, "rollfric": 0.12, "rollfricpw": 0.12,
        "rest": 0.5, "gravz": -1.0, "rotper": 12.0, "capfric": 0.36,
        "caproll": 0.29,
    }
    blob = json.dumps(legacy_canon, sort_keys=True, separators=(",", ":"))
    expected = hashlib.sha256(blob.encode()).hexdigest()[:10]
    assert runner.params_hash({"fric": 0.5, "rollfric": 0.12}, "drum") == expected


def test_drum45_cache_dir_separate_from_drum_and_aor():
    p = {"fric": 0.5, "rollfric": 0.12}
    d45 = runner.trial_dir(p, runner.SEEDS[0], "drum45")
    assert d45.parent.name.startswith("drum45-")
    assert d45 != runner.trial_dir(p, runner.SEEDS[0], "drum")
    assert d45 != runner.trial_dir(p, runner.SEEDS[0], "aor")
    assert runner.params_hash(p, "drum45") != runner.params_hash(p, "drum")


def test_drum45_tag_prefix_safe_for_step_regex():
    tag = runner._tag({"fric": 0.5, "rollfric": 0.12}, runner.SEEDS[0], "drum45")
    assert tag.startswith("drum45") and "-" not in tag and " " not in tag


def test_drum45_argv_has_tilt_and_drum_vars():
    canon = runner.canonical({"fric": 0.5, "rollfric": 0.12}, "drum45")
    trial = runner.trial_dir(canon, runner.SEEDS[0], "drum45")
    argv = runner._build_argv(canon, runner.SEEDS[0], trial, "t_s1", "drum45")
    assert "TILT" in argv and argv[argv.index("TILT") + 1] == "45.0"
    assert "ROTPER" in argv and "CAPFRIC" in argv and "LIFTH" not in argv
    assert str(runner.RESPONSES["drum45"]["template"]) in argv
    assert argv[argv.index("FRICPW") + 1] == "0.36"
    caps = argv[argv.index("CMESH") + 1]
    assert " " not in caps and caps.endswith("drum_caps_r0.075_l0.025.stl")


# ------------------------------------------------- stubbed drum45 engine e2e

def _fake_drum45_engine(angle_deg=43.0, n_frames=17):
    """_launch_sim replacement writing leaning synthetic beds (axial_slope<0:
    bed against the -y cover) at the drum45 steady window."""
    def stub(canon, seed, trial, tag, response="drum45", **kwargs):
        rng = np.random.default_rng(seed % 2**32)
        post = trial / "post"
        frames = [synth.make_drum_bed(angle_deg, rng, axial_slope=-0.8)
                  for _ in range(n_frames)]
        steps = [STEADY45 + 25000 * i for i in range(n_frames)]
        synth.write_dump_series(frames, post, tag, steps)
        synth.write_dump(frames[-1], post / f"{tag}_final.liggghts")
        # pre-window intermediates + mesh STL that must be pruned away
        synth.write_dump(frames[0], post / f"{tag}_50000.liggghts")
        synth.write_dump(frames[0], post / f"{tag}_{STEADY45 - 25000}.liggghts")
        (post / f"{tag}_mesh_50000.stl").write_text("solid x\nendsolid x\n")
        (trial / "run.out").write_text("stub run\n")
    return stub


@pytest.fixture
def cache_to_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "CACHE", tmp_path / "cache")


def test_drum45_run_one_slab_measures_and_prunes(cache_to_tmp, monkeypatch):
    monkeypatch.setattr(runner, "_launch_sim", _fake_drum45_engine(43.0))
    res = runner.run_one({"fric": 0.4001, "rollfric": 0.1374}, runner.SEEDS[0],
                         response="drum45")
    assert abs(res["drum_aor_deg"] - 43.0) < 1.5
    assert res["n_frames"] == 17
    # the leaning bed must NOT trip the lean guard
    assert not any("not leaning" in w for w in res["warnings"])
    trial = Path(res["trial_dir"])
    assert (trial / "measured.json").exists()
    assert (trial / "snapshot.png").exists()
    assert (trial / "snapshot_side.png").exists()   # side_view=True in registry
    assert (trial / "drum_fit.png").exists()
    tag = res["tag"]
    survivors = {p.name for p in (trial / "post").glob("*.liggghts")}
    expected = {f"{tag}_final.liggghts"} | {
        f"{tag}_{STEADY45 + 25000 * i}.liggghts" for i in range(17)}
    assert survivors == expected
    assert not list((trial / "post").glob("*.stl"))


def test_drum45_cache_hit_round_trip(cache_to_tmp, monkeypatch):
    monkeypatch.setattr(runner, "_launch_sim", _fake_drum45_engine(43.0))
    p = {"fric": 0.4001, "rollfric": 0.1374}
    runner.run_one(p, runner.SEEDS[0], response="drum45")

    def explode(*a, **k):
        raise AssertionError("engine launched on a cache hit")
    monkeypatch.setattr(runner, "_launch_sim", explode)
    res = runner.run_one(p, runner.SEEDS[0], response="drum45")
    assert abs(res["drum_aor_deg"] - 43.0) < 1.5


def test_drum45_evaluate_aggregates(cache_to_tmp, monkeypatch):
    monkeypatch.setattr(runner, "_launch_sim", _fake_drum45_engine(44.0))
    res = runner.evaluate({"fric": 0.4001, "rollfric": 0.1374}, n_seeds=2,
                          jobs=2, response="drum45")
    assert res["n_ok"] == 2
    assert abs(res["drum_aor"] - 44.0) < 1.5
    assert res["drum_aor_std"] >= 0.0
    assert res["drum_frame_std"] is not None
