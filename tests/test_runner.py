"""Phase-6 tests for calibration/runner.py — no LIGGGHTS launches.

The engine is stubbed: a fake _launch_sim drops synthetic dumps (via
tests/synth) into the trial's post/ dir, so run_one's real measure/render/
prune/cache logic is exercised end to end in milliseconds. Pure helpers
(canonical, params_hash, MESH relpath, scheduling) are tested directly.
"""

import json
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from calibration import runner  # noqa: E402
from tests import synth  # noqa: E402


# ------------------------------------------------------------- canonical / hash

def test_canonical_defaults_and_mirroring():
    c = runner.canonical({"fric": 0.5, "rollfric": 0.1})
    assert c["fricpw"] == 0.5 and c["rollfricpw"] == 0.1   # wall mirrors particle
    assert c["rest"] == 0.5 and c["gravz"] == -1.0 and c["lifth"] == 0.055


def test_canonical_explicit_wall_friction_kept():
    c = runner.canonical({"fric": 0.5, "rollfric": 0.1, "fricpw": 0.3})
    assert c["fricpw"] == 0.3


def test_canonical_rounds_to_stable_value():
    assert runner.canonical({"fric": 0.5000004, "rollfric": 0.1})["fric"] == 0.5


@pytest.mark.parametrize("bad", [
    {"fric": 1.5, "rollfric": 0.1},     # fric > 1.0
    {"fric": 0.5, "rollfric": 0.9},     # rollfric > 0.5
    {"fric": 0.5, "rollfric": 0.1, "rest": 0.05},  # rest < 0.1
])
def test_canonical_rejects_out_of_range(bad):
    with pytest.raises(ValueError):
        runner.canonical(bad)


def test_params_hash_stable_and_sensitive():
    a = runner.params_hash({"fric": 0.5, "rollfric": 0.1})
    assert a == runner.params_hash({"fric": 0.5, "rollfric": 0.1, "rest": 0.5})
    assert a != runner.params_hash({"fric": 0.6, "rollfric": 0.1})
    # numerically-equal request hashes identically (rounding)
    assert a == runner.params_hash({"fric": 0.50000001, "rollfric": 0.1})


def test_mesh_path_is_space_free():
    # the LIGGGHTS killer: repo root contains a space, MESH must not
    canon = runner.canonical({"fric": 0.5, "rollfric": 0.1})
    trial = runner.trial_dir(canon, runner.SEEDS[0])
    argv = runner._build_argv(canon, runner.SEEDS[0], trial, "t_s1")
    mesh = argv[argv.index("MESH") + 1]
    assert " " not in mesh and mesh.endswith("cylinder_r0.040_h0.100.stl")


def test_tag_has_no_final_or_trailing_digit_confusion():
    # render_trial recovers the tag by stripping _final/_<step>; the tag's own
    # seed suffix (_s<seed>) must survive that.
    canon = runner.canonical({"fric": 0.5, "rollfric": 0.1})
    tag = runner._tag(canon, 49979687)
    assert tag.endswith("_s49979687") and "_final" not in tag


def test_resolve_jobs_clamps_and_honors_override(monkeypatch):
    assert runner._resolve_jobs(7) == 7
    monkeypatch.setenv("RUNNER_JOBS", "3")
    assert runner._resolve_jobs(None) == 3
    monkeypatch.delenv("RUNNER_JOBS")
    assert 1 <= runner._resolve_jobs(None) <= 4


# ------------------------------------------------------------- run_one (stubbed engine)

def _fake_engine(angle_deg=25.0):
    """Return a _launch_sim replacement that writes synthetic final + settle
    dumps (and a couple of intermediates to prove pruning) for the given angle.

    We assert only that the pipeline returns a plausible heap angle, not its
    precision — fit accuracy on synthetic cones is tests/test_measure.py's job,
    and low-count realizations can read several degrees off."""
    def stub(canon, seed, trial, tag, response="aor", **kwargs):
        rng = np.random.default_rng(seed % 2**32)
        post = trial / "post"
        cone = synth.make_cone(angle_deg, rng, n=4000)
        synth.write_dump(cone, post / f"{tag}_final.liggghts")
        synth.write_dump(cone, post / f"{tag}_{runner.SETTLE_STEP}.liggghts")
        # intermediates that must be pruned away
        synth.write_dump(cone, post / f"{tag}_5000.liggghts")
        (post / f"{tag}_mesh_5000.stl").write_text("solid x\nendsolid x\n")
        (trial / "run.out").write_text("stub run\n")
    return stub


@pytest.fixture
def cache_to_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "CACHE", tmp_path / "cache")


def test_run_one_measures_writes_json_and_prunes(cache_to_tmp, monkeypatch):
    monkeypatch.setattr(runner, "_launch_sim", _fake_engine(25.0))
    res = runner.run_one({"fric": 0.5, "rollfric": 0.12}, runner.SEEDS[0])

    assert 10.0 < res["aor_deg"] < 35.0          # plausible heap, pipeline ran
    assert res["seed"] == runner.SEEDS[0]
    trial = Path(res["trial_dir"])
    # self-contained outputs
    assert (trial / "measured.json").exists()
    assert (trial / "snapshot.png").exists()
    assert (trial / "profile_fit.png").exists()
    # pruning: only final + settle dumps survive, no intermediates / STLs
    survivors = {p.name for p in (trial / "post").glob("*")}
    tag = res["tag"]
    assert survivors == {f"{tag}_final.liggghts", f"{tag}_{runner.SETTLE_STEP}.liggghts"}


def test_run_one_cache_hit_skips_engine(cache_to_tmp, monkeypatch):
    monkeypatch.setattr(runner, "_launch_sim", _fake_engine(25.0))
    runner.run_one({"fric": 0.5, "rollfric": 0.12}, runner.SEEDS[0])

    # second call must NOT launch (engine raises if touched)
    def explode(*a, **k):
        raise AssertionError("engine launched on a cache hit")
    monkeypatch.setattr(runner, "_launch_sim", explode)
    res = runner.run_one({"fric": 0.5, "rollfric": 0.12}, runner.SEEDS[0])
    assert 10.0 < res["aor_deg"] < 35.0


def test_run_one_failure_recorded_not_raised(cache_to_tmp, monkeypatch):
    def boom(canon, seed, trial, tag, response="aor", **kwargs):
        raise runner.SimError("timeout after 600s")
    monkeypatch.setattr(runner, "_launch_sim", boom)
    res = runner.run_one({"fric": 0.5, "rollfric": 0.12}, runner.SEEDS[0])
    assert res["failed"] is True and "timeout" in res["error"]
    # a recorded failure is NOT a cache hit -> a later good run reruns
    assert runner._cached(Path(res["trial_dir"])) is None


# ------------------------------------------------------------- evaluate / batch

def test_evaluate_averages_seeds(cache_to_tmp, monkeypatch):
    monkeypatch.setattr(runner, "_launch_sim", _fake_engine(25.0))
    res = runner.evaluate({"fric": 0.5, "rollfric": 0.12}, n_seeds=2, jobs=2)
    assert res["n_ok"] == 2 and res["n_seeds"] == 2
    assert 10.0 < res["aor"] < 35.0
    assert res["bulk_density"] is not None


def test_evaluate_all_seeds_fail_gives_none(cache_to_tmp, monkeypatch):
    monkeypatch.setattr(runner, "_launch_sim",
                        lambda *a, **k: (_ for _ in ()).throw(runner.SimError("x")))
    res = runner.evaluate({"fric": 0.5, "rollfric": 0.12}, n_seeds=2, jobs=2)
    assert res["aor"] is None and res["n_ok"] == 0


def test_evaluate_batch_regroups_per_candidate(cache_to_tmp, monkeypatch):
    monkeypatch.setattr(runner, "_launch_sim", _fake_engine(22.0))
    out = runner.evaluate_batch(
        [{"fric": 0.4, "rollfric": 0.05}, {"fric": 0.6, "rollfric": 0.15}],
        n_seeds=2, jobs=4)
    assert len(out) == 2
    assert all(r["n_ok"] == 2 for r in out)
    # distinct candidates -> distinct cache dirs
    assert out[0]["params"] != out[1]["params"]
