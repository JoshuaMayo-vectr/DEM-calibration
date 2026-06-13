"""Phase-8/9 tests for calibration/optimize.py — no LIGGGHTS launches.

runner.evaluate_multi is stubbed with TWO deterministic analytic surfaces with
different gradient directions — the AoR-only minimum is a LINE (the Phase-8
degeneracy valley) while the combined minimum is a unique point — so the
two-term objective, valley seeding, SQLite resume, best-extraction and
plotting logic run in milliseconds. SQLite storage and the seed csv are
redirected to tmp_path; OUTDIR is monkeypatched so no figure lands in the repo.
"""

import sys
from pathlib import Path

import optuna
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from calibration import optimize, runner  # noqa: E402

optuna.logging.set_verbosity(optuna.logging.WARNING)


# ------------------------------------------------------------- synthetic driver
def _synthetic_aor(params: dict) -> float:
    """Analytic heap surface (Phase-7 shape: rollfric dominant)."""
    return 40.0 * params["fric"] + 100.0 * params["rollfric"] - 4.0


def _synthetic_drum(params: dict) -> float:
    """Analytic drum surface with a DIFFERENT gradient direction, so the
    two target lines cross at exactly one point: fric 0.5966, rollfric 0.0713
    (solve 40f+100r-4=27 and 55f+40r+0.5=36.17)."""
    return 55.0 * params["fric"] + 40.0 * params["rollfric"] + 0.5


JOINT_OPTIMUM = {"fric": 0.5966, "rollfric": 0.0713}


def _fake_evaluate_multi(params, *, responses=("aor", "drum"), n_seeds=2,
                         jobs=None, force=False, material=None) -> dict:
    canon = runner.canonical(params)
    return {
        "aor": _synthetic_aor(canon), "aor_std": 0.4,
        "drum_aor": _synthetic_drum(canon), "drum_aor_std": 0.6,
        "bulk_density": 780.0,
        "n_ok": {"aor": n_seeds, "drum": n_seeds},
        "params": {"aor": canon}, "warnings": [],
    }


@pytest.fixture
def stub_eval(monkeypatch):
    monkeypatch.setattr(optimize.runner, "evaluate_multi", _fake_evaluate_multi)


@pytest.fixture
def study_to_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(optimize, "OUTDIR", tmp_path)
    monkeypatch.setattr(optimize, "STORAGE_URL", f"sqlite:///{tmp_path / 'study.db'}")
    monkeypatch.setattr(optimize, "BEST_JSON", tmp_path / "best.json")
    return tmp_path


def _synth_valley_csv(path: Path) -> None:
    """Rows like results/phase9-drum/valley_check.csv: in-bounds anchors, one
    missing drum_aor (should be skipped), one outside the search box."""
    import pandas as pd
    rows = [
        {"fric": 0.35, "rollfric": 0.18, "rest": 0.60},   # in-bounds
        {"fric": 0.55, "rollfric": 0.12, "rest": 0.45},   # in-bounds
        {"fric": 0.43, "rollfric": 0.03, "rest": 0.42},   # rollfric < 0.05 floor -> skip
        {"fric": 0.40, "rollfric": 0.16, "rest": 0.50},   # drum failed -> skip
    ]
    df = pd.DataFrame(rows)
    df["aor"] = [_synthetic_aor(r) for r in rows]
    df["drum_aor"] = [_synthetic_drum(r) for r in rows]
    df.loc[3, "drum_aor"] = float("nan")
    df["aor_std"] = 0.3
    df["drum_aor_std"] = 0.5
    df.to_csv(path, index=False)


# ------------------------------------------------------------- pure objective
def test_losses_zero_at_target_one_at_sigma():
    assert optimize.aor_loss(27.0) == 0.0
    assert optimize.aor_loss(28.5) == pytest.approx(1.0)
    assert optimize.drum_loss(36.17) == 0.0
    assert optimize.drum_loss(36.17 + 3.1) == pytest.approx(1.0)
    assert optimize.drum_loss(36.17 - 3.1) == pytest.approx(1.0)


def test_losses_none_and_nan_are_penalty():
    assert optimize.aor_loss(None) == optimize.FAIL_PENALTY
    assert optimize.drum_loss(None) == optimize.FAIL_PENALTY
    assert optimize.drum_loss(float("nan")) == optimize.FAIL_PENALTY


def test_objective_composes_both_terms():
    res = {"aor": 28.5, "drum_aor": 36.17 + 3.1, "bulk_density": 780.0}
    assert optimize.objective_from_result(res) == pytest.approx(
        optimize.W_AOR * 1.0 + optimize.W_DRUM * 1.0)
    # perfect on both -> zero
    assert optimize.objective_from_result(
        {"aor": 27.0, "drum_aor": 36.17}) == pytest.approx(0.0)


def test_objective_penalizes_per_missing_response():
    half = optimize.objective_from_result({"aor": 27.0, "drum_aor": None})
    full = optimize.objective_from_result({"aor": None, "drum_aor": None})
    assert half == pytest.approx(optimize.FAIL_PENALTY)
    assert full == pytest.approx(2 * optimize.FAIL_PENALTY)
    assert half < full                      # half-failed is distinguishable


def test_objective_density_term_dormant():
    base = {"aor": 27.0, "drum_aor": 36.17, "bulk_density": 780.0}
    wild = {"aor": 27.0, "drum_aor": 36.17, "bulk_density": 9999.0}
    assert optimize.objective_from_result(base) == optimize.objective_from_result(wild)


# ------------------------------------------------------------- degeneracy break
def test_aor_only_is_degenerate_but_combined_is_not():
    """Two distinct valley points tie on the AoR term; the drum term separates
    them — the entire point of Phase 9, in two assertions."""
    a = {"fric": 0.30, "rollfric": 0.190, "rest": 0.5}   # 40f+100r-4 = 27.0
    b = {"fric": 0.60, "rollfric": 0.070, "rest": 0.5}   # 40f+100r-4 = 27.0
    assert optimize.aor_loss(_synthetic_aor(a)) == pytest.approx(
        optimize.aor_loss(_synthetic_aor(b)), abs=1e-9)
    la = optimize.objective_from_result(
        {"aor": _synthetic_aor(a), "drum_aor": _synthetic_drum(a)})
    lb = optimize.objective_from_result(
        {"aor": _synthetic_aor(b), "drum_aor": _synthetic_drum(b)})
    assert abs(la - lb) > 1.0               # drum breaks the tie decisively


# ------------------------------------------------------------- suggestion space
def test_params_from_trial_suggests_three_dims_in_bounds(study_to_tmp):
    study = optuna.create_study(direction="minimize")
    captured = {}

    def obj(trial):
        p = optimize.params_from_trial(trial)
        captured.update(p)
        for d in optimize.DIMS:
            lo, hi = optimize.SEARCH_BOUNDS[d]
            assert lo <= p[d] <= hi
        return optimize.aor_loss(_synthetic_aor(p))

    study.optimize(obj, n_trials=5)
    assert set(captured) == set(optimize.DIMS)
    assert optimize.SEARCH_BOUNDS["fric"][1] == 0.80   # widened past the 0.60 edge


def test_params_from_trial_searches_wall_friction_when_configured(study_to_tmp):
    # Phase 12: a config that names fricpw/rollfricpw in search_bounds gets them
    # suggested as free dims; absent dims are left to canonical()'s mirror.
    import dataclasses
    cfg = dataclasses.replace(
        optimize.default_config(),
        search_bounds={**optimize.default_config().search_bounds,
                       "fricpw": (0.20, 0.80), "rollfricpw": (0.05, 0.25)})
    study = optuna.create_study(direction="minimize")
    captured = {}

    def obj(trial):
        p = optimize.params_from_trial(trial, cfg)
        captured.update(p)
        return optimize.aor_loss(_synthetic_aor(p))

    study.optimize(obj, n_trials=3)
    assert set(captured) == {"fric", "rollfric", "rest", "fricpw", "rollfricpw"}


def test_params_from_trial_searches_cohesion_when_configured(study_to_tmp):
    # Phase 13: a config naming cohed in search_bounds gets it suggested as a free dim
    import dataclasses
    cfg = dataclasses.replace(
        optimize.default_config(),
        search_bounds={**optimize.default_config().search_bounds,
                       "cohed": (1000.0, 30000.0)})
    study = optuna.create_study(direction="minimize")
    captured = {}

    def obj(trial):
        p = optimize.params_from_trial(trial, cfg)
        captured.update(p)
        return optimize.aor_loss(_synthetic_aor(p))

    study.optimize(obj, n_trials=3)
    assert set(captured) == {"fric", "rollfric", "rest", "cohed"}
    assert 1000.0 <= captured["cohed"] <= 30000.0


def test_make_objective_records_user_attrs(stub_eval, study_to_tmp):
    study = optimize.build_study(sampler="tpe")
    study.optimize(optimize.make_objective(), n_trials=1)
    t = study.trials[0]
    assert t.user_attrs["aor"] is not None
    assert t.user_attrs["drum_aor"] is not None
    assert t.user_attrs["n_ok"] == {"aor": 2, "drum": 2}
    assert "hash" in t.user_attrs and "hash_drum" in t.user_attrs
    res = _fake_evaluate_multi({d: t.params[d] for d in optimize.DIMS})
    assert t.value == pytest.approx(optimize.objective_from_result(res))


# ------------------------------------------------------------- valley seeding
def test_seed_from_valley_skips_nan_and_out_of_bounds(stub_eval, study_to_tmp):
    csv = study_to_tmp / "valley.csv"
    _synth_valley_csv(csv)
    study = optimize.build_study(sampler="tpe")
    n = optimize.seed_from_valley(study, csv_path=csv)
    assert n == 2                       # 4 rows - 1 NaN drum - 1 below floor
    study.optimize(optimize.make_objective(), n_trials=2)
    ran = {(round(t.params["fric"], 3), round(t.params["rollfric"], 3))
           for t in study.trials}
    assert (0.35, 0.18) in ran and (0.55, 0.12) in ran


def test_seed_from_valley_idempotent_on_resume(stub_eval, study_to_tmp):
    csv = study_to_tmp / "valley.csv"
    _synth_valley_csv(csv)
    study = optimize.build_study(sampler="tpe")
    first = optimize.seed_from_valley(study, csv_path=csv)
    study.optimize(optimize.make_objective(), n_trials=first)
    assert optimize.seed_from_valley(study, csv_path=csv) == 0


def test_seed_from_valley_missing_csv_returns_zero(study_to_tmp):
    study = optimize.build_study(sampler="tpe")
    assert optimize.seed_from_valley(study, csv_path=study_to_tmp / "nope.csv") == 0


# ------------------------------------------------------------- SQLite resume
def test_study_resumes_from_sqlite(stub_eval, study_to_tmp):
    s1 = optimize.build_study(sampler="tpe")
    s1.optimize(optimize.make_objective(), n_trials=5)
    best_after_5 = s1.best_value
    del s1

    s2 = optimize.build_study(sampler="tpe")
    assert len(s2.trials) == 5
    s2.optimize(optimize.make_objective(), n_trials=5)
    assert len(s2.trials) == 10
    assert s2.best_value <= best_after_5


def test_reset_clears_prior_trials(stub_eval, study_to_tmp):
    s1 = optimize.build_study(sampler="tpe")
    s1.optimize(optimize.make_objective(), n_trials=3)
    s2 = optimize.build_study(sampler="tpe", reset=True)
    assert len(s2.trials) == 0


def test_phase8_study_storage_untouched(stub_eval, study_to_tmp):
    """Building/running the Phase-9 study must not write to the frozen
    Phase-8 storage path."""
    phase8_db = REPO / "results" / "phase8-optimizer" / "study.db"
    before = phase8_db.stat().st_mtime if phase8_db.exists() else None
    study = optimize.build_study(sampler="tpe")
    study.optimize(optimize.make_objective(), n_trials=2)
    after = phase8_db.stat().st_mtime if phase8_db.exists() else None
    assert before == after


# ------------------------------------------------------------- convergence
def test_optimize_converges_to_the_joint_optimum(stub_eval, study_to_tmp):
    study = optimize.build_study(sampler="tpe")
    study.optimize(optimize.make_objective(), n_trials=60)
    assert study.best_value < 0.6            # noiseless stub: near the crossing
    best = study.best_params
    assert abs(best["fric"] - JOINT_OPTIMUM["fric"]) < 0.12
    assert abs(best["rollfric"] - JOINT_OPTIMUM["rollfric"]) < 0.06


# ------------------------------------------------------------- best extraction
def test_best_records_sorted_with_drum_fields(stub_eval, study_to_tmp):
    study = optimize.build_study(sampler="tpe")
    study.optimize(optimize.make_objective(), n_trials=8)
    recs = optimize.best_records(study, n=3)
    assert len(recs) == 3
    losses = [r["loss"] for r in recs]
    assert losses == sorted(losses)
    assert recs[0]["trial_dir"] and recs[0]["hash"] and recs[0]["hash_drum"]
    assert recs[0]["aor"] is not None and recs[0]["drum_aor"] is not None


def test_write_best_both_bands_verdict(stub_eval, study_to_tmp):
    study = optimize.build_study(sampler="tpe")
    study.optimize(optimize.make_objective(), n_trials=80)
    import json
    payload = json.loads(optimize.write_best(study).read_text())
    assert payload["target_drum"] == optimize.TARGET_DRUM
    if payload["target_met"]:
        assert abs(payload["best"]["aor"] - optimize.TARGET_AOR) <= optimize.TARGET_SIGMA
        assert abs(payload["best"]["drum_aor"] - optimize.TARGET_DRUM) <= optimize.SIGMA_DRUM
    # on the noiseless stub with 80 trials the crossing must be found
    assert payload["target_met"] is True


# ------------------------------------------------------------- visualization
def test_make_plots_and_search3d_write_files(stub_eval, study_to_tmp):
    study = optimize.build_study(sampler="tpe")
    study.optimize(optimize.make_objective(), n_trials=12)
    figs = optimize.make_plots(study, outdir=study_to_tmp)
    names = {p.name for p in figs}
    assert "history.png" in names and "contour.png" in names
    assert "valley_compare.png" in names
    for p in figs:
        assert p.exists() and p.stat().st_size > 0
    html = optimize.make_search3d(study, out_path=study_to_tmp / "search3d.html")
    assert html.exists() and html.stat().st_size > 0


# ------------------------------------------------------------- registry metadata
def test_registry_calib_metadata_consistent():
    """The calib blocks (UI checkbox list = objective metadata = gallery spec)
    must stay consistent with the rest of the repo's single sources."""
    from calibration import screen

    required = {"label", "result_key", "std_key", "fit_png",
                "target", "sigma", "weight", "holdout"}
    calibratable = {n: s for n, s in runner.RESPONSES.items() if "calib" in s}
    assert {"aor", "drum", "drum45"} <= set(calibratable)
    for name, spec in calibratable.items():
        assert required <= set(spec["calib"]), f"{name} missing calib keys"
        assert spec["calib"]["sigma"] > 0
    # values must not fork from their existing single sources
    assert runner.RESPONSES["aor"]["calib"]["target"] == screen.TARGET_AOR
    assert runner.RESPONSES["aor"]["calib"]["sigma"] == screen.TARGET_SIGMA
    assert runner.RESPONSES["drum"]["calib"]["target"] == optimize.TARGET_DRUM
    assert runner.RESPONSES["drum"]["calib"]["sigma"] == optimize.SIGMA_DRUM
    # the Phase-10 hold-out must never be offered for calibration
    assert runner.RESPONSES["drum45"]["calib"]["holdout"] is True
    assert runner.RESPONSES["aor"]["calib"]["holdout"] is False
    assert runner.RESPONSES["drum"]["calib"]["holdout"] is False


# ------------------------------------------------------------- study config
def test_default_config_matches_constants(study_to_tmp):
    cfg = optimize.default_config()
    assert cfg.study_name == optimize.STUDY_NAME
    assert Path(cfg.outdir) == Path(optimize.OUTDIR)
    assert cfg.storage_url == optimize.STORAGE_URL
    assert Path(cfg.best_json) == Path(optimize.BEST_JSON)
    assert cfg.responses["aor"] == {"enabled": True, "target": optimize.TARGET_AOR,
                                    "sigma": optimize.TARGET_SIGMA,
                                    "weight": optimize.W_AOR}
    assert cfg.responses["drum"] == {"enabled": True, "target": optimize.TARGET_DRUM,
                                     "sigma": optimize.SIGMA_DRUM,
                                     "weight": optimize.W_DRUM}
    assert cfg.search_bounds == {d: tuple(optimize.SEARCH_BOUNDS[d])
                                 for d in optimize.DIMS}
    assert cfg.sampler == "gp" and cfg.sampler_seed == 12345
    assert cfg.n_seeds == 2 and cfg.trials == 40 and cfg.jobs is None
    assert cfg.enabled_responses() == ("aor", "drum")
    floor = (optimize.W_AOR * optimize.AOR_NOISE_DEG / optimize.TARGET_SIGMA
             + optimize.W_DRUM * optimize.DRUM_NOISE_DEG / optimize.SIGMA_DRUM)
    assert cfg.noise_floor() == pytest.approx(floor)


def test_config_roundtrip_fixed_point(study_to_tmp):
    cfg = optimize.default_config()
    p1 = optimize.save_config(cfg, study_to_tmp / "a" / "config.json")
    cfg2 = optimize.load_config(p1)
    p2 = optimize.save_config(cfg2, study_to_tmp / "b" / "config.json")
    assert p1.read_text() == p2.read_text()          # save∘load is a fixed point
    assert cfg2.responses == cfg.responses
    assert cfg2.search_bounds == cfg.search_bounds
    assert cfg2.study_name == cfg.study_name
    # paths serialize repo-relative (portable to the Linux box)
    raw = __import__("json").loads(p1.read_text())
    assert not raw["seed_csv"].startswith("/")


def test_load_config_rejects_bad_inputs(study_to_tmp):
    import dataclasses
    import json as _json

    cfg = optimize.default_config()
    base = study_to_tmp / "config.json"

    # enabling the Phase-10 hold-out must raise
    bad = dataclasses.replace(cfg, responses={
        **cfg.responses,
        "drum45": {"enabled": True, "target": 43.65, "sigma": 2.92, "weight": 1.0}})
    optimize.save_config(bad, base)
    with pytest.raises(ValueError, match="hold-out"):
        optimize.load_config(base)

    # unknown response name
    raw = _json.loads(optimize.save_config(cfg, base).read_text())
    raw["responses"]["bogus"] = {"enabled": True, "target": 1, "sigma": 1, "weight": 1}
    base.write_text(_json.dumps(raw))
    with pytest.raises(ValueError, match="unknown response"):
        optimize.load_config(base)

    # bounds outside runner.RANGES
    bad = dataclasses.replace(cfg, search_bounds={**cfg.search_bounds,
                                                  "fric": (0.0, 0.8)})
    optimize.save_config(bad, base)
    with pytest.raises(ValueError, match="search_bounds"):
        optimize.load_config(base)

    # nothing enabled
    bad = dataclasses.replace(cfg, responses={
        n: {**rc, "enabled": False} for n, rc in cfg.responses.items()})
    optimize.save_config(bad, base)
    with pytest.raises(ValueError, match="no response enabled"):
        optimize.load_config(base)

    # Phase 12: unknown search dimension
    raw = _json.loads(optimize.save_config(cfg, base).read_text())
    raw["search_bounds"]["bogusdim"] = [0.1, 0.2]
    base.write_text(_json.dumps(raw))
    with pytest.raises(ValueError, match="unknown dimension"):
        optimize.load_config(base)

    # Phase 12: missing a required base dim
    raw = _json.loads(optimize.save_config(cfg, base).read_text())
    del raw["search_bounds"]["rest"]
    base.write_text(_json.dumps(raw))
    with pytest.raises(ValueError, match="base dims"):
        optimize.load_config(base)

    # Phase 12: wall bound outside runner.RANGES
    raw = _json.loads(optimize.save_config(cfg, base).read_text())
    raw["search_bounds"]["fricpw"] = [0.0, 0.8]   # lo < runner.RANGES fricpw 0.1
    base.write_text(_json.dumps(raw))
    with pytest.raises(ValueError, match="search_bounds"):
        optimize.load_config(base)


def test_config_roundtrip_with_wall_friction_bounds(study_to_tmp):
    # a Phase-12 wall-enabled config survives save -> load -> save unchanged
    import dataclasses
    cfg = dataclasses.replace(
        optimize.default_config(),
        search_bounds={**optimize.default_config().search_bounds,
                       "fricpw": (0.30, 0.70), "rollfricpw": (0.05, 0.20)})
    p1 = optimize.save_config(cfg, study_to_tmp / "w" / "config.json")
    loaded = optimize.load_config(p1)
    assert loaded.search_bounds["fricpw"] == (0.30, 0.70)
    assert loaded.search_bounds["rollfricpw"] == (0.05, 0.20)
    # canonical SEARCHABLE_DIMS ordering preserved
    assert list(loaded.search_bounds) == ["fric", "rollfric", "rest",
                                          "fricpw", "rollfricpw"]


_COHESIVE_MAT = {"name": "wet-maize", "particle_density_kgm3": 1250.0,
                 "psd_mm": [[6.0, 0.3], [7.0, 0.5], [8.0, 0.2]],
                 "youngs_modulus_pa": 1.0e7, "timestep_s": None,
                 "n_particles": 1200, "cohesion": "sjkr"}


def test_load_config_rejects_cohesion_without_cohesive_material(study_to_tmp):
    # Phase 13: cohed is meaningless without SJKR active (material.cohesion='sjkr')
    import dataclasses
    cfg = dataclasses.replace(
        optimize.default_config(),                       # material None -> cohesionless
        search_bounds={**optimize.default_config().search_bounds,
                       "cohed": (1000.0, 30000.0)})
    base = study_to_tmp / "c" / "config.json"
    optimize.save_config(cfg, base)
    with pytest.raises(ValueError):
        optimize.load_config(base)


def test_config_roundtrip_with_cohesion_and_cohesive_material(study_to_tmp):
    import dataclasses
    cfg = dataclasses.replace(
        optimize.default_config(), material=_COHESIVE_MAT,
        search_bounds={**optimize.default_config().search_bounds,
                       "cohed": (1000.0, 30000.0)})
    p1 = optimize.save_config(cfg, study_to_tmp / "cc" / "config.json")
    loaded = optimize.load_config(p1)
    assert loaded.search_bounds["cohed"] == (1000.0, 30000.0)
    assert loaded.material["cohesion"] == "sjkr"
    # fixed point
    again = optimize.load_config(optimize.save_config(
        loaded, study_to_tmp / "cc2" / "config.json"))
    assert again.material == loaded.material
    assert again.search_bounds == loaded.search_bounds


def test_objective_with_custom_cfg(study_to_tmp):
    import dataclasses

    cfg = optimize.default_config()
    res = {"aor": 28.5, "drum_aor": 36.17 + 3.1, "bulk_density": 780.0}
    # doubling the drum weight doubles its term
    heavy = dataclasses.replace(cfg, responses={
        **cfg.responses,
        "drum": {**cfg.responses["drum"], "weight": 2.0}})
    assert optimize.objective_from_result(res, heavy) == pytest.approx(
        optimize.W_AOR * 1.0 + 2.0 * 1.0)
    # disabling drum removes its term entirely (even a failed drum)
    aor_only = dataclasses.replace(cfg, responses={
        **cfg.responses,
        "drum": {**cfg.responses["drum"], "enabled": False}})
    assert aor_only.enabled_responses() == ("aor",)
    assert optimize.objective_from_result(
        {"aor": 28.5, "drum_aor": None}, aor_only) == pytest.approx(1.0)


def test_write_best_resolves_monkeypatched_path_at_call_time(stub_eval, study_to_tmp):
    """Pins the contamination fix: with no explicit path, write_best must land
    in the (monkeypatched) module BEST_JSON — the def-time default-arg binding
    this replaces wrote a test artifact into results/phase9-drum/best.json."""
    study = optimize.build_study(sampler="tpe")
    study.optimize(optimize.make_objective(), n_trials=2)
    out = optimize.write_best(study)
    assert Path(out) == study_to_tmp / "best.json"
    assert out.exists()


def test_phase9_best_json_untouched_by_suite(stub_eval, study_to_tmp):
    """The frozen Phase-9 artifacts must survive a default-config run."""
    sentinel = REPO / "results" / "phase9-drum" / "best.json"
    before = sentinel.stat().st_mtime if sentinel.exists() else None
    study = optimize.build_study(sampler="tpe")
    study.optimize(optimize.make_objective(), n_trials=2)
    optimize.write_best(study)
    after = sentinel.stat().st_mtime if sentinel.exists() else None
    assert before == after


def test_cli_run_and_resume_with_config(stub_eval, study_to_tmp, monkeypatch, capsys):
    """The Phase-8.5 exit criterion in miniature: a config file drives the
    bare CLI; the study lands in the config's outdir under the config's name;
    resume --config grows the same study."""
    import dataclasses
    import json as _json

    outdir = study_to_tmp / "studies" / "ui-test"
    cfg = dataclasses.replace(optimize.default_config(),
                              study_name="ui-test", outdir=outdir,
                              trials=3, seed_csv=None, sampler="tpe")
    config = optimize.save_config(cfg, outdir / "config.json")

    monkeypatch.setattr(sys, "argv",
                        ["optimize.py", "run", "--config", str(config),
                         "--no-hero"])
    optimize.main()
    assert (outdir / "study.db").exists()
    payload = _json.loads((outdir / "best.json").read_text())
    assert payload["study_name"] == "ui-test"
    assert payload["n_trials"] == 3

    monkeypatch.setattr(sys, "argv",
                        ["optimize.py", "resume", "--config", str(config),
                         "--trials", "2", "--no-hero"])
    optimize.main()
    payload = _json.loads((outdir / "best.json").read_text())
    assert payload["n_trials"] == 5                  # same study, grown

    import optuna as _optuna
    study = _optuna.load_study(study_name="ui-test",
                               storage=f"sqlite:///{outdir / 'study.db'}")
    assert len(study.trials) == 5


def _hero_test_config(study_to_tmp, name="hero-test"):
    import dataclasses

    outdir = study_to_tmp / "studies" / name
    cfg = dataclasses.replace(optimize.default_config(), study_name=name,
                              outdir=outdir, trials=2, seed_csv=None,
                              sampler="tpe")
    return optimize.save_config(cfg, outdir / "config.json")


def test_run_spawns_hero_detached(stub_eval, study_to_tmp, monkeypatch):
    """After write_best, `run --config` detaches `video.py hero`; --no-hero
    suppresses it. Popen is captured — no real render in tests."""
    config = _hero_test_config(study_to_tmp)
    spawned = []

    class FakeProc:
        pid = 4242

    def fake_popen(argv, **kw):
        spawned.append((argv, kw))
        return FakeProc()

    monkeypatch.setattr("subprocess.Popen", fake_popen)
    monkeypatch.setattr(sys, "argv",
                        ["optimize.py", "run", "--config", str(config)])
    optimize.main()
    assert len(spawned) == 1
    argv, kw = spawned[0]
    assert argv[1].endswith("video.py") and argv[2] == "hero"
    assert "--config" in argv and str(config) in argv
    assert kw["start_new_session"] is True

    spawned.clear()
    monkeypatch.setattr(sys, "argv",
                        ["optimize.py", "resume", "--config", str(config),
                         "--no-hero"])
    optimize.main()
    assert spawned == []                             # opt-out honored


def test_config_v2_material_roundtrip(study_to_tmp):
    """A material block survives save -> load (fixed point), and the loaded
    config is what the objective hands the runner."""
    import dataclasses

    material = {"name": "maize", "particle_density_kgm3": 1250.0,
                "psd_mm": [[6.0, 0.3], [7.0, 0.5], [8.0, 0.2]],
                "youngs_modulus_pa": 1.0e7, "timestep_s": None,
                "n_particles": 1200}
    cfg = dataclasses.replace(optimize.default_config(),
                              outdir=study_to_tmp / "m", seed_csv=None,
                              material=material)
    path = optimize.save_config(cfg, study_to_tmp / "m" / "config.json")
    raw = __import__("json").loads(path.read_text())
    assert raw["schema_version"] == 4                         # Phase 15 bumped 3 -> 4
    assert raw["material"]["name"] == "maize"
    assert "geometry" not in raw                              # default geometry omitted
    assert "particle_shape" not in raw["material"]            # default shape omitted

    loaded = optimize.load_config(path)
    assert loaded.material["psd_mm"] == material["psd_mm"]
    again = optimize.load_config(optimize.save_config(
        loaded, study_to_tmp / "m" / "config2.json"))
    assert again.material == loaded.material                  # fixed point


def test_config_v1_and_default_material_stay_default(study_to_tmp):
    """v1 configs (no material key) and v2 configs spelling out the wheat
    values both load as material=None — the legacy cache namespace."""
    import dataclasses
    import json as _json

    cfg = dataclasses.replace(optimize.default_config(),
                              outdir=study_to_tmp / "v1", seed_csv=None)
    path = optimize.save_config(cfg, study_to_tmp / "v1" / "config.json")
    raw = _json.loads(path.read_text())
    assert "material" not in raw
    raw["schema_version"] = 1                                  # simulate an old file
    path.write_text(_json.dumps(raw))
    assert optimize.load_config(path).material is None

    raw["schema_version"] = 2
    raw["material"] = dict(runner.WHEAT_MATERIAL)              # explicit wheat
    path.write_text(_json.dumps(raw))
    assert optimize.load_config(path).material is None


def test_config_v3_contact_model_and_geometry_roundtrip(study_to_tmp):
    """Phase-14: an epsd rolling model + a non-default cylinder survive
    save -> load to a fixed point, write the schema with a geometry block, and
    activate the rollvisc search dimension."""
    import dataclasses

    material = {**dict(runner.WHEAT_MATERIAL), "name": "wheat-epsd-big",
                "rolling_model": "epsd", "cyl_radius_m": 0.050, "cyl_height_m": 0.120}
    cfg = dataclasses.replace(
        optimize.default_config(), outdir=study_to_tmp / "g", seed_csv=None,
        material=material,
        search_bounds={"fric": (0.2, 0.8), "rollfric": (0.05, 0.25),
                       "rest": (0.3, 0.7), "rollvisc": (0.0, 0.5)})
    path = optimize.save_config(cfg, study_to_tmp / "g" / "config.json")
    raw = __import__("json").loads(path.read_text())
    assert raw["schema_version"] == 4
    assert raw["material"]["rolling_model"] == "epsd"
    assert raw["geometry"] == {"cyl_radius_m": 0.050, "cyl_height_m": 0.120}

    loaded = optimize.load_config(path)
    assert loaded.material["rolling_model"] == "epsd"
    assert loaded.material["cyl_radius_m"] == 0.050
    assert "rollvisc" in loaded.search_bounds
    again = optimize.load_config(optimize.save_config(
        loaded, study_to_tmp / "g" / "config2.json"))
    assert again.material == loaded.material                  # fixed point


def test_config_v4_multisphere_roundtrip(study_to_tmp):
    """Phase-15: a multisphere clump survives save -> load to a fixed point,
    writes a v4 schema with particle_shape + clump_spheres in the material block,
    and gets its own cache namespace (≠ the single-sphere wheat hash)."""
    import dataclasses

    clump = [[0.0, 0.0, -0.0026, 0.00175], [0.0, 0.0, 0.0, 0.00200],
             [0.0, 0.0, 0.0026, 0.00175]]
    material = {**dict(runner.WHEAT_MATERIAL), "name": "wheat-prolate",
                "particle_shape": "multisphere", "clump_spheres": clump}
    cfg = dataclasses.replace(optimize.default_config(),
                              outdir=study_to_tmp / "ms", seed_csv=None,
                              material=material)
    path = optimize.save_config(cfg, study_to_tmp / "ms" / "config.json")
    raw = __import__("json").loads(path.read_text())
    assert raw["schema_version"] == 4
    assert raw["material"]["particle_shape"] == "multisphere"
    assert len(raw["material"]["clump_spheres"]) == 3

    loaded = optimize.load_config(path)
    assert loaded.material["particle_shape"] == "multisphere"
    again = optimize.load_config(optimize.save_config(
        loaded, study_to_tmp / "ms" / "config2.json"))
    assert again.material == loaded.material                  # fixed point
    # own namespace: a multisphere study cannot collide with the wheat baseline
    assert runner.params_hash({"fric": 0.5, "rollfric": 0.12}, "aor",
                              loaded.material) != "a3338ce730"


def test_config_rejects_rollvisc_without_epsd(study_to_tmp):
    """rollvisc is meaningless unless the rolling model is epsd/epsd3."""
    import dataclasses
    import json as _json

    cfg = dataclasses.replace(
        optimize.default_config(), outdir=study_to_tmp / "rv", seed_csv=None,
        search_bounds={"fric": (0.2, 0.8), "rollfric": (0.05, 0.25),
                       "rest": (0.3, 0.7), "rollvisc": (0.0, 0.5)})
    path = optimize.save_config(cfg, study_to_tmp / "rv" / "config.json")
    # default material is epsd2 -> must reject
    with pytest.raises(ValueError, match="rollvisc"):
        optimize.load_config(path)
    # flip the material to epsd -> now accepted
    raw = _json.loads(path.read_text())
    raw["material"] = {**dict(runner.WHEAT_MATERIAL), "rolling_model": "epsd"}
    path.write_text(_json.dumps(raw))
    assert "rollvisc" in optimize.load_config(path).search_bounds


def test_config_rejects_bad_material(study_to_tmp):
    import dataclasses
    import json as _json

    cfg = dataclasses.replace(optimize.default_config(),
                              outdir=study_to_tmp / "bad", seed_csv=None)
    path = optimize.save_config(cfg, study_to_tmp / "bad" / "config.json")
    raw = _json.loads(path.read_text())
    raw["material"] = {"psd_mm": [[0.01, 1.0]]}                # absurd diameter
    path.write_text(_json.dumps(raw))
    with pytest.raises(ValueError, match="material"):
        optimize.load_config(path)


def test_objective_threads_material_to_runner(study_to_tmp, monkeypatch):
    import dataclasses

    seen = {}

    def spy_evaluate_multi(params, *, responses, n_seeds, jobs, material=None):
        seen["material"] = material
        return _fake_evaluate_multi(params, responses=responses, n_seeds=n_seeds)

    monkeypatch.setattr(optimize.runner, "evaluate_multi", spy_evaluate_multi)
    material = {"name": "maize", "particle_density_kgm3": 1250.0,
                "psd_mm": [[6.0, 0.3], [7.0, 0.5], [8.0, 0.2]],
                "youngs_modulus_pa": 1.0e7, "timestep_s": None,
                "n_particles": 1200}
    cfg = dataclasses.replace(optimize.default_config(),
                              outdir=study_to_tmp / "obj", seed_csv=None,
                              trials=1, material=material)
    study = optimize.build_study(sampler="tpe", cfg=cfg)
    study.optimize(optimize.make_objective(cfg=cfg), n_trials=1)
    assert seen["material"] == material
    # the stored hash lives in the material's namespace, not the legacy one
    t = study.trials[0]
    assert t.user_attrs["hash"] == runner.params_hash(t.params, "aor", material)
    assert t.user_attrs["hash"] != runner.params_hash(t.params, "aor")
    # and best.json records the physics for provenance
    optimize.write_best(study, cfg=cfg)
    payload = __import__("json").loads(cfg.best_json.read_text())
    assert payload["material"]["name"] == "maize"


def test_hero_spawn_failure_never_fails_the_run(stub_eval, study_to_tmp,
                                                monkeypatch, capsys):
    config = _hero_test_config(study_to_tmp, name="hero-boom")

    def boom(*a, **kw):
        raise OSError("no fork for you")

    monkeypatch.setattr("subprocess.Popen", boom)
    monkeypatch.setattr(sys, "argv",
                        ["optimize.py", "run", "--config", str(config)])
    optimize.main()                                  # must not raise
    captured = capsys.readouterr()
    assert "hero video spawn skipped" in captured.err
    assert '"best"' in captured.out                  # the run still reported
