"""Phase-9 tests for the runner's response registry — no LIGGGHTS launches.

Two contracts under test: (1) the drum response works end to end through the
stubbed engine (cache layout, pruning, multi-frame measurement, aggregation,
evaluate_multi merging); (2) the "aor" response is BYTE-COMPATIBLE with the
pre-Phase-9 runner — same canonical dict, same hash, same cache paths — so
the Phase 7/8 results/cache/<hash>/ dirs stay valid.
"""

import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from calibration import runner  # noqa: E402
from tests import synth  # noqa: E402

STEADY = runner.RESPONSES["drum"]["steady_step"]


# ------------------------------------------------- legacy byte-compatibility

def test_aor_hash_pinned():
    """The Phase 7/8 cache contract: this hash must NEVER change. Pinned from
    the pre-Phase-9 runner (canonical keys fric/fricpw/rollfric/rollfricpw/
    rest/lifth/gravz, sort_keys json, sha256[:10])."""
    import hashlib
    import json
    legacy_canon = {
        "fric": 0.5, "fricpw": 0.5, "rollfric": 0.12, "rollfricpw": 0.12,
        "rest": 0.5, "lifth": 0.055, "gravz": -1.0,
    }
    blob = json.dumps(legacy_canon, sort_keys=True, separators=(",", ":"))
    expected = hashlib.sha256(blob.encode()).hexdigest()[:10]
    assert runner.params_hash({"fric": 0.5, "rollfric": 0.12}) == expected
    # and the default-response path layout is unchanged
    trial = runner.trial_dir({"fric": 0.5, "rollfric": 0.12}, runner.SEEDS[0])
    assert trial == runner.CACHE / expected / f"seed{runner.SEEDS[0]}"


def test_aor_canonical_unchanged_by_response_arg():
    assert runner.canonical({"fric": 0.5, "rollfric": 0.1}) == \
        runner.canonical({"fric": 0.5, "rollfric": 0.1}, "aor")


# ------------------------------------------------------- drum canonical/hash

def test_drum_canonical_has_protocol_knobs_not_lifth():
    c = runner.canonical({"fric": 0.5, "rollfric": 0.1}, "drum")
    # cover friction defaults to the wheat-acrylic published values — a fixed
    # protocol input independent of the wheat-wheat search
    assert c["rotper"] == 12.0 and c["capfric"] == 0.36 and c["caproll"] == 0.29
    assert "lifth" not in c


def test_drum_cover_friction_overridable():
    c = runner.canonical({"fric": 0.5, "rollfric": 0.1,
                          "capfric": 0.4, "caproll": 0.1}, "drum")
    assert c["capfric"] == 0.4 and c["caproll"] == 0.1
    # cover friction is hash-relevant: a cap-sensitivity run gets its own cache
    assert runner.params_hash({"fric": 0.5, "rollfric": 0.1}, "drum") != \
        runner.params_hash({"fric": 0.5, "rollfric": 0.1, "capfric": 0.4}, "drum")


def test_drum_cache_dir_is_prefixed_and_separate():
    p = {"fric": 0.5, "rollfric": 0.12}
    aor_dir = runner.trial_dir(p, runner.SEEDS[0], "aor")
    drum_dir = runner.trial_dir(p, runner.SEEDS[0], "drum")
    assert drum_dir != aor_dir
    assert drum_dir.parent.name.startswith("drum-")
    assert not aor_dir.parent.name.startswith("drum-")


def test_drum_tag_prefix_safe_for_step_regex():
    tag = runner._tag({"fric": 0.5, "rollfric": 0.12}, runner.SEEDS[0], "drum")
    assert tag.startswith("drum") and "-" not in tag and " " not in tag


def test_drum_argv_has_drum_vars():
    canon = runner.canonical({"fric": 0.5, "rollfric": 0.12}, "drum")
    trial = runner.trial_dir(canon, runner.SEEDS[0], "drum")
    argv = runner._build_argv(canon, runner.SEEDS[0], trial, "t_s1", "drum")
    assert "ROTPER" in argv and "CAPFRIC" in argv and "LIFTH" not in argv
    assert str(runner.RESPONSES["drum"]["template"]) in argv
    mesh = argv[argv.index("MESH") + 1]
    assert " " not in mesh and mesh.endswith("drum_r0.075_l0.025.stl")
    caps = argv[argv.index("CMESH") + 1]
    assert " " not in caps and caps.endswith("drum_caps_r0.075_l0.025.stl")


def test_unknown_response_rejected():
    with pytest.raises(ValueError):
        runner.canonical({"fric": 0.5, "rollfric": 0.1}, "hopper")


# ------------------------------------------------- stubbed drum engine e2e

def _fake_drum_engine(angle_deg=30.0, n_frames=17):
    """_launch_sim replacement writing a synthetic steady frame series plus
    spin-up intermediates (to prove drum pruning keeps the window only)."""
    def stub(canon, seed, trial, tag, response="drum", **kwargs):
        rng = np.random.default_rng(seed % 2**32)
        post = trial / "post"
        frames = [synth.make_drum_bed(angle_deg, rng) for _ in range(n_frames)]
        steps = [STEADY + 25000 * i for i in range(n_frames)]
        synth.write_dump_series(frames, post, tag, steps)
        synth.write_dump(frames[-1], post / f"{tag}_final.liggghts")
        # pre-window intermediates + mesh STL that must be pruned away
        synth.write_dump(frames[0], post / f"{tag}_50000.liggghts")
        synth.write_dump(frames[0], post / f"{tag}_{STEADY - 25000}.liggghts")
        (post / f"{tag}_mesh_50000.stl").write_text("solid x\nendsolid x\n")
        (trial / "run.out").write_text("stub run\n")
    return stub


@pytest.fixture
def cache_to_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "CACHE", tmp_path / "cache")


def test_drum_run_one_measures_and_prunes(cache_to_tmp, monkeypatch):
    monkeypatch.setattr(runner, "_launch_sim", _fake_drum_engine(30.0))
    res = runner.run_one({"fric": 0.5, "rollfric": 0.12}, runner.SEEDS[0],
                         response="drum")
    assert abs(res["drum_aor_deg"] - 30.0) < 1.5
    assert res["n_frames"] == 17
    trial = Path(res["trial_dir"])
    assert (trial / "measured.json").exists()
    assert (trial / "snapshot.png").exists()
    assert (trial / "drum_fit.png").exists()
    # pruning: final + all 17 steady frames survive; spin-up frames + STL gone
    tag = res["tag"]
    survivors = {p.name for p in (trial / "post").glob("*.liggghts")}
    expected = {f"{tag}_final.liggghts"} | {
        f"{tag}_{STEADY + 25000 * i}.liggghts" for i in range(17)}
    assert survivors == expected
    assert not list((trial / "post").glob("*.stl"))


def test_drum_cache_hit_requires_drum_key(cache_to_tmp, monkeypatch):
    monkeypatch.setattr(runner, "_launch_sim", _fake_drum_engine(30.0))
    res = runner.run_one({"fric": 0.5, "rollfric": 0.12}, runner.SEEDS[0],
                         response="drum")
    trial = Path(res["trial_dir"])
    assert runner._cached(trial, "drum") is not None
    # the same measured.json is NOT a valid aor cache entry
    assert runner._cached(trial, "aor") is None

    def explode(*a, **k):
        raise AssertionError("engine launched on a cache hit")
    monkeypatch.setattr(runner, "_launch_sim", explode)
    res2 = runner.run_one({"fric": 0.5, "rollfric": 0.12}, runner.SEEDS[0],
                          response="drum")
    assert abs(res2["drum_aor_deg"] - 30.0) < 1.5


def test_drum_evaluate_aggregates(cache_to_tmp, monkeypatch):
    monkeypatch.setattr(runner, "_launch_sim", _fake_drum_engine(28.0))
    res = runner.evaluate({"fric": 0.5, "rollfric": 0.12}, n_seeds=2, jobs=2,
                          response="drum")
    assert res["n_ok"] == 2
    assert abs(res["drum_aor"] - 28.0) < 1.5
    assert res["drum_aor_std"] >= 0.0
    assert res["drum_frame_std"] is not None


# --------------------------------------------------------- evaluate_multi

def _fake_dual_engine(aor_angle=25.0, drum_angle=31.0, fail_response=None):
    """Engine stub that serves BOTH responses (dispatches on the response
    arg), optionally failing one of them."""
    aor_stub = None
    drum_stub = _fake_drum_engine(drum_angle)

    def stub(canon, seed, trial, tag, response="aor", **kwargs):
        if response == fail_response:
            raise runner.SimError(f"injected {response} failure")
        if response == "drum":
            drum_stub(canon, seed, trial, tag, response)
            return
        rng = np.random.default_rng(seed % 2**32)
        post = trial / "post"
        cone = synth.make_cone(aor_angle, rng, n=4000)
        synth.write_dump(cone, post / f"{tag}_final.liggghts")
        synth.write_dump(cone, post / f"{tag}_{runner.SETTLE_STEP}.liggghts")
        (trial / "run.out").write_text("stub run\n")
    return stub


def test_evaluate_multi_merges_both_responses(cache_to_tmp, monkeypatch):
    monkeypatch.setattr(runner, "_launch_sim", _fake_dual_engine())
    res = runner.evaluate_multi({"fric": 0.5, "rollfric": 0.12}, n_seeds=2, jobs=4)
    assert res["n_ok"] == {"aor": 2, "drum": 2}
    assert 10.0 < res["aor"] < 35.0
    assert abs(res["drum_aor"] - 31.0) < 1.5
    assert res["bulk_density"] is not None
    assert set(res["responses"]) == {"aor", "drum"}


def test_evaluate_multi_one_response_failure_isolated(cache_to_tmp, monkeypatch):
    monkeypatch.setattr(runner, "_launch_sim",
                        _fake_dual_engine(fail_response="drum"))
    res = runner.evaluate_multi({"fric": 0.5, "rollfric": 0.12}, n_seeds=2, jobs=4)
    assert res["n_ok"]["aor"] == 2 and res["n_ok"]["drum"] == 0
    assert res["aor"] is not None
    assert res["drum_aor"] is None
    assert any("failed" in w for w in res["warnings"])


def test_evaluate_multi_reuses_single_response_cache(cache_to_tmp, monkeypatch):
    """A prior evaluate(response='drum') must be a cache hit inside
    evaluate_multi — the M4 valley-check seeding pattern."""
    monkeypatch.setattr(runner, "_launch_sim", _fake_dual_engine())
    runner.evaluate({"fric": 0.5, "rollfric": 0.12}, n_seeds=2, jobs=2,
                    response="drum")

    launched = []

    def tracking(canon, seed, trial, tag, response="aor", **kwargs):
        launched.append(response)
        _fake_dual_engine()(canon, seed, trial, tag, response)
    monkeypatch.setattr(runner, "_launch_sim", tracking)
    res = runner.evaluate_multi({"fric": 0.5, "rollfric": 0.12}, n_seeds=2, jobs=4)
    assert res["n_ok"] == {"aor": 2, "drum": 2}
    assert launched == ["aor", "aor"]   # drum came from cache
