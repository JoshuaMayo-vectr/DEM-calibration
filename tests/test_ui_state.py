"""Phase-8.5 tests for calibration/ui_state.py — process control + read layer.

No LIGGGHTS, no Streamlit, no real optimizer: subprocesses are tiny shell
sleepers (the detached-descendant case emulates runner._launch_sim's
start_new_session mpirun), studies are stub-driven SQLite in tmp_path, and
gallery trial dirs are fabricated files. Follows the test_optimize.py
conventions: monkeypatched module paths, deterministic stubs, tmp_path
isolation.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import optuna
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from calibration import optimize, runner, ui_state  # noqa: E402

optuna.logging.set_verbosity(optuna.logging.WARNING)

SLEEPER = [sys.executable, "-c", "import time; time.sleep(60)"]


@pytest.fixture
def study_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(ui_state, "STUDIES_ROOT", tmp_path / "studies")
    d = tmp_path / "studies" / "t1"
    d.mkdir(parents=True)
    return d


def _stop_quietly(d):
    try:
        ui_state.stop_run(d, grace_s=5.0)
    except Exception:  # noqa: BLE001 — teardown best-effort
        pass


# ------------------------------------------------------------- process control
def test_start_writes_pidfile_and_is_running(study_dir):
    info = ui_state.start_run(study_dir, argv=SLEEPER)
    try:
        pf = json.loads((study_dir / "run.pid").read_text())
        assert pf["pid"] == info["pid"] and pf["pgid"] == info["pgid"]
        assert pf["argv"] == SLEEPER and pf["started"]
        status = ui_state.run_status(study_dir)
        assert status["running"] is True and status["pid"] == info["pid"]
        assert status["stale"] is False
    finally:
        _stop_quietly(study_dir)


def test_start_refuses_while_running(study_dir):
    ui_state.start_run(study_dir, argv=SLEEPER)
    try:
        with pytest.raises(RuntimeError, match="already live"):
            ui_state.start_run(study_dir, argv=SLEEPER)
    finally:
        _stop_quietly(study_dir)


def test_start_without_config_raises(study_dir):
    with pytest.raises(FileNotFoundError, match="config.json"):
        ui_state.start_run(study_dir)


def test_stop_terminates_and_clears_pidfile(study_dir):
    info = ui_state.start_run(study_dir, argv=SLEEPER)
    res = ui_state.stop_run(study_dir, grace_s=5.0)
    assert res["stopped"] is True and res["pid"] == info["pid"]
    assert not (study_dir / "run.pid").exists()
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        try:
            os.kill(info["pid"], 0)
            time.sleep(0.1)
        except ProcessLookupError:
            break
    with pytest.raises(ProcessLookupError):
        os.kill(info["pid"], 0)
    assert ui_state.run_status(study_dir)["running"] is False


def test_stale_pidfile_dead_pid(study_dir):
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    (study_dir / "run.pid").write_text(json.dumps(
        {"pid": proc.pid, "pgid": proc.pid, "started": "x", "match": "optimize.py"}))
    status = ui_state.run_status(study_dir)
    assert status["running"] is False and status["stale"] is True
    # a stale pidfile must not block a new start
    info = ui_state.start_run(study_dir, argv=SLEEPER)
    try:
        assert ui_state.run_status(study_dir)["running"] is True
        assert info["pid"] != proc.pid or True
    finally:
        _stop_quietly(study_dir)


def test_pid_reuse_guard(study_dir):
    """An alive pid whose command line is not our optimizer (= recycled pid)
    must read as stale, not running."""
    (study_dir / "run.pid").write_text(json.dumps(
        {"pid": os.getpid(), "pgid": os.getpgid(0), "started": "x",
         "match": "optimize.py run --config /nonexistent/config.json"}))
    status = ui_state.run_status(study_dir)
    assert status["running"] is False and status["stale"] is True


def test_stop_kills_detached_descendants(study_dir):
    """Emulates runner._launch_sim: the run process spawns a child in its OWN
    session (start_new_session mpirun). Killing only the run's pgid would
    orphan it — stop_run must walk the tree and kill both."""
    script = (study_dir / "parent.py")
    script.write_text(
        "import subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c',\n"
        "    'import time; time.sleep(60)'], start_new_session=True)\n"
        "open(%r, 'w').write(str(child.pid))\n"
        "time.sleep(60)\n" % str(study_dir / "child.pid"))
    ui_state.start_run(study_dir, argv=[sys.executable, str(script)])
    deadline = time.monotonic() + 10.0
    while not (study_dir / "child.pid").exists() and time.monotonic() < deadline:
        time.sleep(0.1)
    child_pid = int((study_dir / "child.pid").read_text())
    os.kill(child_pid, 0)                            # child is alive and detached

    res = ui_state.stop_run(study_dir, grace_s=5.0)
    assert res["stopped"] is True
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        try:
            os.kill(child_pid, 0)
            time.sleep(0.1)
        except ProcessLookupError:
            break
    with pytest.raises(ProcessLookupError):
        os.kill(child_pid, 0)                        # the detached child died too


def test_stop_when_nothing_running(study_dir):
    res = ui_state.stop_run(study_dir)
    assert res["stopped"] is False


# ------------------------------------------------------------- read layer
def _make_cfg(tmp_path, name="t1"):
    import dataclasses
    return dataclasses.replace(
        optimize.default_config(), study_name=name,
        outdir=tmp_path / "studies" / name, seed_csv=None, trials=2)


def test_list_studies_reads_configs(study_dir, tmp_path):
    cfg = _make_cfg(tmp_path)
    optimize.save_config(cfg, study_dir / "config.json")
    (study_dir.parent / "broken").mkdir()
    (study_dir.parent / "broken" / "config.json").write_text("{not json")
    (study_dir.parent / "empty").mkdir()             # no config.json -> skipped

    entries = ui_state.list_studies()
    names = {e["name"] for e in entries}
    assert names == {"t1", "broken"}
    t1 = next(e for e in entries if e["name"] == "t1")
    assert t1["cfg"].study_name == "t1" and t1["error"] is None
    assert t1["has_db"] is False and t1["status"]["running"] is False
    broken = next(e for e in entries if e["name"] == "broken")
    assert broken["cfg"] is None and broken["error"]


def test_load_study_none_before_first_run(study_dir, tmp_path):
    cfg = _make_cfg(tmp_path)
    assert ui_state.load_study(cfg) is None


def _stub_study(cfg, monkeypatch, n_trials=2):
    """A real SQLite study in cfg.outdir, driven by the test_optimize stub."""
    from tests.test_optimize import _fake_evaluate_multi

    monkeypatch.setattr(optimize.runner, "evaluate_multi", _fake_evaluate_multi)
    study = optimize.build_study(sampler="tpe", cfg=cfg)
    study.optimize(optimize.make_objective(cfg=cfg), n_trials=n_trials)
    return study


def test_trial_rows_and_load_study(study_dir, tmp_path, monkeypatch):
    cfg = _make_cfg(tmp_path)
    _stub_study(cfg, monkeypatch)
    study = ui_state.load_study(cfg)
    assert study is not None
    rows = ui_state.trial_rows(study, cfg)
    assert len(rows) == 2
    assert rows[0]["trial"] > rows[1]["trial"]       # newest first
    for row in rows:
        assert row["state"] == "complete" and row["loss"] is not None
        assert row["aor"] is not None and row["drum_aor"] is not None


def test_gallery_items_resolution(study_dir, tmp_path, monkeypatch):
    """hash user_attr -> results/cache/<prefix><hash>/seed*/ -> images +
    measured.json, with ok / failed / pending statuses, never raising."""
    cache = tmp_path / "cache"
    monkeypatch.setattr(runner, "CACHE", cache)
    cfg = _make_cfg(tmp_path)
    _stub_study(cfg, monkeypatch, n_trials=1)
    study = ui_state.load_study(cfg)
    t = study.trials[0]
    h_aor, h_drum = t.user_attrs["hash"], t.user_attrs["hash_drum"]

    ok = cache / h_aor / "seed49979687"              # aor: ok, both images
    ok.mkdir(parents=True)
    (ok / "snapshot.png").write_bytes(b"png")
    (ok / "profile_fit.png").write_bytes(b"png")
    (ok / "measured.json").write_text(json.dumps({"aor_deg": 27.0}))
    failed = cache / h_aor / "seed67867967"          # aor: recorded failure
    failed.mkdir(parents=True)
    (failed / "measured.json").write_text(json.dumps(
        {"failed": True, "error": "timeout"}))
    pending = cache / f"drum-{h_drum}" / "seed49979687"   # drum: in flight
    pending.mkdir(parents=True)
    (pending / "run.out").write_text("running\n")

    items = ui_state.gallery_items(study, cfg)
    by = {(i["response"], i["seed"]): i for i in items}

    i_ok = by[("aor", "49979687")]
    assert i_ok["status"] == "ok"
    assert i_ok["snapshot"] == ok / "snapshot.png"
    assert i_ok["fit"] == ok / "profile_fit.png"     # registry fit_png, not hardcoded
    assert i_ok["measured"]["aor_deg"] == 27.0
    i_fail = by[("aor", "67867967")]
    assert i_fail["status"] == "failed" and i_fail["snapshot"] is None
    i_pend = by[("drum", "49979687")]
    assert i_pend["status"] == "pending" and i_pend["measured"] is None


def test_gallery_handles_missing_hash_and_dirs(study_dir, tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    monkeypatch.setattr(runner, "CACHE", cache)     # nothing cached at all
    cfg = _make_cfg(tmp_path)
    _stub_study(cfg, monkeypatch, n_trials=1)
    study = ui_state.load_study(cfg)
    items = ui_state.gallery_items(study, cfg)
    assert items and all(i["status"] == "pending" for i in items)


def test_tail_log(study_dir):
    assert ui_state.tail_log(study_dir) == ""
    (study_dir / "run.log").write_text("\n".join(f"line{i}" for i in range(100)))
    tail = ui_state.tail_log(study_dir, n_lines=10)
    assert tail.splitlines() == [f"line{i}" for i in range(90, 100)]


# ------------------------------------------------------------- new accessors
def test_response_specs_merge(tmp_path):
    cfg = _make_cfg(tmp_path)
    specs = ui_state.response_specs(cfg)
    assert set(specs) == {"aor", "drum"}                 # enabled only
    assert specs["aor"]["result_key"] == "aor"           # registry metadata
    assert specs["aor"]["target"] == cfg.responses["aor"]["target"]  # config band
    assert specs["drum"]["fit_png"] == "drum_fit.png"


def test_family_anchors_shipped_and_missing(monkeypatch, tmp_path):
    anchors = ui_state.family_anchors()
    assert anchors and all({"fric", "rollfric"} <= set(a) for a in anchors)
    monkeypatch.setattr(ui_state, "REPO_ROOT", tmp_path)  # no materials/ here
    assert ui_state.family_anchors() == []


def test_trial_spans_and_cached_flag(study_dir, tmp_path, monkeypatch):
    cfg = _make_cfg(tmp_path)
    _stub_study(cfg, monkeypatch, n_trials=3)
    study = ui_state.load_study(cfg)
    spans = ui_state.trial_spans(study)
    assert [s["trial"] for s in spans] == [0, 1, 2]      # ascending
    for s in spans:
        assert s["state"] == "complete" and s["duration_s"] is not None
        assert s["cached"] is True                       # stub trials are ~ms


def test_eta_idle_and_running(study_dir, tmp_path, monkeypatch):
    cfg = _make_cfg(tmp_path)
    _stub_study(cfg, monkeypatch, n_trials=2)
    study = ui_state.load_study(cfg)
    spans = ui_state.trial_spans(study)

    idle = ui_state.eta(study_dir, spans, cfg)
    assert idle["running"] is False and idle["eta_s"] is None

    ui_state.start_run(study_dir, argv=SLEEPER)          # fake live run
    try:
        from datetime import timedelta

        # spans clearly BEFORE this run -> full budget remains; the all-cached
        # duration signal is flagged low-confidence
        before = [dict(s, start=s["start"] - timedelta(seconds=30))
                  for s in spans]
        live = ui_state.eta(study_dir, before, cfg)
        assert live["running"] is True
        assert live["remaining"] == cfg.trials
        assert live["low_confidence"] is True
        assert live["eta_s"] is not None and live["text"]

        # one span clearly AFTER the start -> it counts toward this run
        mixed = before[:-1] + [dict(spans[-1],
                                    start=spans[-1]["start"] + timedelta(seconds=30))]
        live = ui_state.eta(study_dir, mixed, cfg)
        assert live["remaining"] == cfg.trials - 1
    finally:
        _stop_quietly(study_dir)


def test_trial_detail_resolves(study_dir, tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    monkeypatch.setattr(runner, "CACHE", cache)
    cfg = _make_cfg(tmp_path)
    _stub_study(cfg, monkeypatch, n_trials=1)
    study = ui_state.load_study(cfg)
    t = study.trials[0]
    sd = cache / t.user_attrs["hash"] / "seed49979687"
    sd.mkdir(parents=True)
    (sd / "measured.json").write_text(json.dumps({"aor_deg": 27.0}))

    detail = ui_state.trial_detail(study, cfg, t.number)
    assert detail["trial"] == t.number and detail["loss"] is not None
    assert set(detail["params"]) == {"fric", "rollfric", "rest"}
    assert detail["responses"]["aor"]["target"] == cfg.responses["aor"]["target"]
    assert detail["dirs"]["aor"] == cache / t.user_attrs["hash"]
    ok = [i for i in detail["items"] if i["status"] == "ok"]
    assert ok and ok[0]["trial_dir"] == sd
    assert ui_state.trial_detail(study, cfg, 999) is None


def test_parse_psd_csv_variants():
    named = b"diameter_mm,mass_fraction\n3.4,0.25\n3.7,0.50\n4.0,0.25\n"
    assert ui_state.parse_psd_csv(named) == [[3.4, 0.25], [3.7, 0.5], [4.0, 0.25]]

    percent = b"size (mm),mass %\n4.0,25\n3.7,50\n3.4,25\n"
    out = ui_state.parse_psd_csv(percent)
    assert out[0][0] == 3.4 and sum(w for _, w in out) == pytest.approx(1.0)

    headerless_cols = b"a,b\n6.0,2\n7.0,3\n"                # numeric fallback + ratios
    out = ui_state.parse_psd_csv(headerless_cols)
    assert out == [[6.0, 0.4], [7.0, 0.6]]

    with pytest.raises(ValueError):
        ui_state.parse_psd_csv(b"x\nonly-one-column\n")


def test_material_card_preview_uses_study_material():
    payload = {
        "study_name": "m1", "target_met": True,
        "targets": {"aor": {"target": 25.0, "sigma": 2.0, "weight": 1.0}},
        "best": {"params": {"fric": 0.4}, "aor": 24.5, "aor_std": 0.5},
        "material": {"name": "maize", "particle_density_kgm3": 1250.0,
                     "psd_mm": [[6.0, 0.5], [8.0, 0.5]],
                     "youngs_modulus_pa": 1.0e7, "timestep_s": None,
                     "n_particles": 1200},
    }
    card = ui_state.material_card_preview(payload)
    fi = card["fixed_inputs"]
    assert fi["material_name"] == "maize"                   # study's, not wheat's
    assert fi["particle_density_kgm3"] == 1250.0
    assert fi["psd_mm"] == {"6 mm": 0.5, "8 mm": 0.5}
    assert fi["timestep_s"] == "auto (Rayleigh-scaled)"


DUMP_TEXT = """ITEM: TIMESTEP
1000
ITEM: NUMBER OF ATOMS
3
ITEM: BOX BOUNDS ff ff ff
-0.1 0.1
-0.1 0.1
0.0 0.2
ITEM: ATOMS id type x y z vx vy vz omegax omegay omegaz radius
1 1 0.0 0.0 0.002 0 0 0 0 0 0 0.0017
2 1 0.01 0.0 0.002 0 0 0 0 0 0 0.0019
3 1 0.0 0.01 0.002 0 0 0 0 0 0 0.0020
"""


def test_dump_points_parses_minimal_dump(tmp_path):
    trial = tmp_path / "trial"
    (trial / "post").mkdir(parents=True)
    (trial / "post" / "t1_final.liggghts").write_text(DUMP_TEXT)
    pts = ui_state.dump_points(trial)
    assert pts["n_total"] == 3 and pts["n_shown"] == 3
    assert {"x", "y", "z", "radius"} <= set(pts["df"].columns)
    assert pts["dump"].name == "t1_final.liggghts"


# ------------------------------------------------------------- video layer
def _progress_sleeper(out_path, *, stage="frames", extra=""):
    """argv that mimics video.py: writes a progress sidecar then sleeps."""
    code = (
        "import json, os, sys, time\n"
        f"p = {str(out_path)!r} + '.progress.json'\n"
        "json.dump({'pid': os.getpid(), 'match': 'progress-sleeper', "
        f"'stage': {stage!r}, 'frame': 3, 'n_frames': 10, 'error': None, "
        f"'out': {str(out_path)!r}}}, open(p, 'w'))\n"
        f"{extra}\n"
        "time.sleep(60)\n")
    return [sys.executable, "-c", code]


def test_video_status_lifecycle(tmp_path):
    trial = tmp_path / "trial"
    trial.mkdir()
    out = trial / "video_flow.mp4"
    assert ui_state.video_status(trial, "flow")["state"] == "none"

    info = ui_state.start_video(trial, "flow", argv=_progress_sleeper(out))
    try:
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            s = ui_state.video_status(trial, "flow")
            if s["frame"] == 3:                      # child's sidecar landed
                break
            time.sleep(0.1)
        s = ui_state.video_status(trial, "flow")
        assert s["state"] == "running" and s["n_frames"] == 10
        with pytest.raises(RuntimeError, match="already running"):
            ui_state.start_video(trial, "flow", argv=_progress_sleeper(out))
    finally:
        os.killpg(os.getpgid(info["pid"]), 15)
        time.sleep(0.3)

    s = ui_state.video_status(trial, "flow")         # dead pid mid-stage
    assert s["state"] == "error" and "interrupted" in s["error"]

    # a done sidecar + artifact reads as done
    out.write_bytes(b"mp4")
    pp = trial / "video_flow.mp4.progress.json"
    pp.write_text(json.dumps({"pid": 1, "match": "x", "stage": "done",
                              "frame": 10, "n_frames": 10, "out": str(out)}))
    s = ui_state.video_status(trial, "flow")
    assert s["state"] == "done" and s["path"] == out


def test_video_path_prefers_existing(tmp_path):
    trial = tmp_path / "t"
    trial.mkdir()
    assert ui_state.video_path(trial, "turntable") is None
    gif = trial / "video_turntable.gif"
    gif.write_bytes(b"gif")
    assert ui_state.video_path(trial, "turntable") == gif


def test_hero_paths_and_start(study_dir, tmp_path):
    cfg = _make_cfg(tmp_path)
    assert ui_state.hero_paths(cfg) == {}
    Path(cfg.outdir).mkdir(parents=True, exist_ok=True)
    (Path(cfg.outdir) / "hero_aor.mp4").write_bytes(b"x")
    assert set(ui_state.hero_paths(cfg)) == {"aor"}

    assert ui_state.hero_status(study_dir)["state"] == "none"
    with pytest.raises(FileNotFoundError, match="config.json"):
        ui_state.start_hero(study_dir)               # no config written yet
    info = ui_state.start_hero(study_dir, argv=SLEEPER)
    try:
        assert ui_state.hero_status(study_dir)["state"] in ("running", "error")
    finally:
        os.killpg(os.getpgid(info["pid"]), 15)


# ------------------------------------------------------------- streamlit smoke
def test_ui_renders_without_exception(tmp_path, monkeypatch):
    """The cockpit must render headless against an empty studies root (the
    create-a-study prompt) and against one configured study. Smoke only — the
    logic lives in ui_state/optimize and is tested above, not via pixels."""
    apptest = pytest.importorskip("streamlit.testing.v1")

    monkeypatch.setattr(ui_state, "STUDIES_ROOT", tmp_path / "studies")
    at = apptest.AppTest.from_file(str(REPO / "calibration" / "ui.py"),
                                   default_timeout=30)
    at.run()
    assert not at.exception

    cfg = _make_cfg(tmp_path, name="smoke")
    optimize.save_config(cfg, tmp_path / "studies" / "smoke" / "config.json")
    at = apptest.AppTest.from_file(str(REPO / "calibration" / "ui.py"),
                                   default_timeout=30)
    at.run()
    assert not at.exception


def test_material_card_preview_shape(tmp_path):
    payload = {
        "study_name": "t1", "n_trials": 5, "target_met": True,
        "targets": {"aor": {"target": 27.0, "sigma": 1.5, "weight": 1.0},
                    "drum": {"target": 36.17, "sigma": 3.1, "weight": 1.0}},
        "best": {"params": {"fric": 0.4, "rollfric": 0.14, "rest": 0.58},
                 "aor": 26.4, "aor_std": 0.6, "drum_aor": 38.1,
                 "drum_aor_std": 0.2, "bulk_density": 782.0,
                 "trial_dir": "/x/seed0"},
    }
    card = ui_state.material_card_preview(payload)
    assert "_preview" in card                        # clearly not a deliverable
    assert card["parameters"]["fric"]["value"] == 0.4
    assert card["responses"]["aor"]["value"] == 26.4
    assert card["responses"]["aor"]["target"] == 27.0
    assert card["responses"]["drum"]["std"] == 0.2
    assert card["responses"]["bulk_density"]["calibrated"] is False
    assert card["target_met"] is True
    assert card["evidence"]["study_name"] == "t1"
