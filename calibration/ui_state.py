"""Process control + read layer for the Phase-8.5 calibration UI.

The ONLY place pidfile / subprocess logic for UI-launched optimizer runs
lives. No Streamlit imports — everything here is unit-testable headless, and
ui.py stays a pure view over it. The design rule (ROADMAP Phase 8.5): the UI
owns no calibration logic and invents no state — a study is its directory
(results/studies/<name>/ holding config.json, study.db, best.json, run.log,
run.pid, figures) plus the shared results/cache/ trial dirs, and every
function here just reads or launches against those files.

Stop semantics: the optimizer subprocess gets its own session, but so does
every mpirun it launches (runner._launch_sim start_new_session=True) — killing
the optimizer's process group alone would orphan in-flight sims for up to
wall_limit (1200 s drum). stop_run therefore snapshots the descendant tree
FIRST and signals each descendant process group too. Killing mid-trial is safe
by construction: per-trial SQLite commits (Phase-8 SIGKILL lesson) + the
runner's stale-partial wipe on the next visit.
"""

import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from calibration import optimize, runner, video  # noqa: E402

STUDIES_ROOT = REPO_ROOT / "results" / "studies"
PYTHON = REPO_ROOT / ".venv" / "bin" / "python"
OPTIMIZE_PY = REPO_ROOT / "calibration" / "optimize.py"
VIDEO_PY = REPO_ROOT / "calibration" / "video.py"

PIDFILE = "run.pid"
LOGFILE = "run.log"
VIDEO_LOG = "video.log"


# ------------------------------------------------------------- process control

def _pidfile(study_dir: Path) -> Path:
    return Path(study_dir) / PIDFILE


def _proc_tree() -> list[tuple[int, int, int]]:
    """(pid, ppid, pgid) for every visible process — `ps -axo` parsed.
    POSIX-portable (macOS now, the Linux deployment target later)."""
    out = subprocess.run(["ps", "-axo", "pid=,ppid=,pgid="],
                         capture_output=True, text=True, check=True).stdout
    rows = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 3:
            try:
                rows.append((int(parts[0]), int(parts[1]), int(parts[2])))
            except ValueError:
                continue
    return rows


def _descendant_pgids(root_pid: int) -> set[int]:
    """Process groups of every descendant of root_pid (the detached mpirun
    sessions the optimizer's own pgid does not cover)."""
    rows = _proc_tree()
    children: dict[int, list[int]] = {}
    pgid_of: dict[int, int] = {}
    for pid, ppid, pgid in rows:
        children.setdefault(ppid, []).append(pid)
        pgid_of[pid] = pgid
    pgids: set[int] = set()
    stack = list(children.get(root_pid, []))
    while stack:
        pid = stack.pop()
        pgids.add(pgid_of[pid])
        stack.extend(children.get(pid, []))
    return pgids


def _cmdline(pid: int) -> str:
    """Command line of pid, '' if gone. Used as the PID-reuse guard."""
    try:
        return subprocess.run(["ps", "-o", "command=", "-p", str(pid)],
                              capture_output=True, text=True).stdout.strip()
    except OSError:
        return ""


def run_status(study_dir: Path) -> dict:
    """{'running', 'pid', 'stale', 'started'} for a study dir. Alive means the
    pid exists AND its command line still looks like our optimizer run (a
    recycled pid must not read as a live calibration)."""
    pf = _pidfile(study_dir)
    if not pf.exists():
        return {"running": False, "pid": None, "stale": False, "started": None}
    try:
        info = json.loads(pf.read_text())
        pid = int(info["pid"])
    except (ValueError, KeyError, json.JSONDecodeError):
        return {"running": False, "pid": None, "stale": True, "started": None}
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return {"running": False, "pid": pid, "stale": True,
                "started": info.get("started")}
    cmd = _cmdline(pid)
    expect = info.get("match", "optimize.py")
    if expect not in cmd:
        return {"running": False, "pid": pid, "stale": True,
                "started": info.get("started")}
    return {"running": True, "pid": pid, "stale": False,
            "started": info.get("started")}


def start_run(study_dir: Path, *, resume: bool = False,
              argv: list[str] | None = None) -> dict:
    """Launch `optimize.py run|resume --config <study_dir>/config.json` as a
    detached subprocess; stdout+stderr append to run.log; write run.pid
    atomically. Refuses while a run is live; clears a stale pidfile. The argv
    override exists solely for tests (a fake sleeper instead of the real
    optimizer). Returns the pidfile dict."""
    study_dir = Path(study_dir)
    status = run_status(study_dir)
    if status["running"]:
        raise RuntimeError(f"a run is already live (pid {status['pid']}) — stop it first")
    if status["stale"]:
        _pidfile(study_dir).unlink(missing_ok=True)

    config = study_dir / "config.json"
    if argv is None:
        if not config.exists():
            raise FileNotFoundError(f"no config.json in {study_dir} — configure first")
        argv = [str(PYTHON), str(OPTIMIZE_PY), "resume" if resume else "run",
                "--config", str(config)]
        match = f"optimize.py {'resume' if resume else 'run'} --config {config}"
    else:
        # skip argv[0]: macOS ps rewrites it to the resolved binary (the venv
        # symlink becomes the framework Python), so only the args are stable
        match = " ".join(argv[1:]) if len(argv) > 1 else argv[0]

    study_dir.mkdir(parents=True, exist_ok=True)
    log = open(study_dir / LOGFILE, "ab")  # noqa: SIM115 — handle passes to the child
    try:
        proc = subprocess.Popen(
            argv, cwd=REPO_ROOT, stdin=subprocess.DEVNULL,
            stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    finally:
        log.close()

    info = {
        "pid": proc.pid,
        "pgid": os.getpgid(proc.pid),
        "started": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "argv": argv,
        "cmd": "resume" if resume else "run",
        # substring run_status greps for in `ps -o command=` (PID-reuse guard)
        "match": match,
    }
    tmp = _pidfile(study_dir).with_suffix(".pid.tmp")
    tmp.write_text(json.dumps(info, indent=2))
    tmp.rename(_pidfile(study_dir))
    return info


def stop_run(study_dir: Path, *, grace_s: float = 10.0) -> dict:
    """Stop a live run AND its detached sim sessions. SIGTERM first (optimizer
    pgid + every descendant pgid, snapshotted before signaling), escalate to
    SIGKILL after grace_s, remove the pidfile. Returns {'stopped', 'pid',
    'killed': [pgids]}. Safe under resume semantics: at most the in-flight
    trial is lost (stale RUNNING row, ignored by the samplers)."""
    study_dir = Path(study_dir)
    status = run_status(study_dir)
    if not status["running"]:
        _pidfile(study_dir).unlink(missing_ok=True)
        return {"stopped": False, "pid": status["pid"], "killed": []}

    pid = status["pid"]
    info = json.loads(_pidfile(study_dir).read_text())
    own_pgid = int(info.get("pgid", pid))
    # snapshot BEFORE signaling — once the parent dies the tree is unwalkable
    pgids = {own_pgid} | _descendant_pgids(pid)

    for sig in (signal.SIGTERM, signal.SIGKILL):
        for pgid in pgids:
            try:
                os.killpg(pgid, sig)
            except (ProcessLookupError, PermissionError):
                continue
        deadline = time.monotonic() + grace_s
        while time.monotonic() < deadline:
            if not _any_alive(pgids):
                break
            time.sleep(0.2)
        if not _any_alive(pgids):
            break

    _pidfile(study_dir).unlink(missing_ok=True)
    return {"stopped": True, "pid": pid, "killed": sorted(pgids)}


def _any_alive(pgids: set[int]) -> bool:
    alive_pgids = {pgid for _, _, pgid in _proc_tree()}
    return bool(pgids & alive_pgids)


# ------------------------------------------------------------- read layer

def study_dir(name: str) -> Path:
    return STUDIES_ROOT / name


def list_studies(root: Path | None = None) -> list[dict]:
    """Every results/studies/<name>/ with a config.json, newest-config first:
    {'name', 'dir', 'cfg', 'has_db', 'status'}. A broken config is reported,
    not raised — one bad dir must not blank the whole UI."""
    root = Path(root) if root is not None else STUDIES_ROOT
    out = []
    if not root.exists():
        return out
    for d in sorted(root.iterdir()):
        config = d / "config.json"
        if not config.is_file():
            continue
        entry = {"name": d.name, "dir": d, "cfg": None, "error": None,
                 "has_db": (d / "study.db").exists(),
                 "status": run_status(d)}
        try:
            entry["cfg"] = optimize.load_config(config)
        except (ValueError, KeyError, json.JSONDecodeError) as err:
            entry["error"] = str(err)
        out.append(entry)
    out.sort(key=lambda e: (e["dir"] / "config.json").stat().st_mtime, reverse=True)
    return out


def load_study(cfg: "optimize.StudyConfig"):
    """Read-only optuna.load_study (the optuna-dashboard-proven concurrent-
    SQLite pattern — all writes stay in the run subprocess). None if the study
    doesn't exist yet."""
    import optuna

    if not (Path(cfg.outdir) / "study.db").exists():
        return None
    try:
        return optuna.load_study(
            study_name=cfg.study_name,
            storage=optuna.storages.RDBStorage(cfg.storage_url))
    except KeyError:
        return None


def trial_rows(study, cfg: "optimize.StudyConfig") -> list[dict]:
    """One flat dict per trial, newest first — the live table."""
    import optuna

    rows = []
    for t in study.get_trials(deepcopy=False):
        row = {"trial": t.number, "state": t.state.name.lower(),
               "loss": t.value if t.state == optuna.trial.TrialState.COMPLETE else None}
        row.update({d: t.params.get(d) for d in optimize.DIMS})
        for r in cfg.enabled_responses():
            calib = runner.RESPONSES[r]["calib"]
            row[calib["result_key"]] = t.user_attrs.get(calib["result_key"])
            row[calib["std_key"]] = t.user_attrs.get(calib["std_key"])
        rows.append(row)
    rows.sort(key=lambda r: r["trial"], reverse=True)
    return rows


def _items_for_trial(t, cfg: "optimize.StudyConfig") -> list[dict]:
    """Gallery items for one optuna trial — see gallery_items for semantics."""
    items = []
    for r in cfg.enabled_responses():
        spec = runner.RESPONSES[r]
        h = t.user_attrs.get(optimize._hash_attr(r))
        if not h:
            items.append({"trial": t.number, "response": r, "seed": None,
                          "status": "running", "snapshot": None,
                          "fit": None, "measured": None, "trial_dir": None})
            continue
        base = runner.CACHE / f"{spec['dir_prefix']}{h}"
        seed_dirs = sorted(base.glob("seed*")) if base.exists() else []
        if not seed_dirs:
            items.append({"trial": t.number, "response": r, "seed": None,
                          "status": "pending", "snapshot": None,
                          "fit": None, "measured": None, "trial_dir": None})
            continue
        for sd in seed_dirs:
            snapshot = sd / "snapshot.png"
            fit = sd / spec["calib"]["fit_png"]
            measured = None
            status = "pending"
            mj = sd / "measured.json"
            if mj.exists():
                try:
                    measured = json.loads(mj.read_text())
                except (json.JSONDecodeError, OSError):
                    measured = None
                if measured is None:
                    status = "pending"
                elif measured.get(spec["success_key"]) is not None:
                    status = "ok"
                elif measured.get("failed"):
                    status = "failed"
            items.append({
                "trial": t.number, "response": r,
                "seed": sd.name.removeprefix("seed"),
                "status": status,
                "snapshot": snapshot if snapshot.exists() else None,
                "fit": fit if fit.exists() else None,
                "measured": measured,
                "trial_dir": sd,
            })
    return items


def gallery_items(study, cfg: "optimize.StudyConfig", *,
                  newest_first: bool = True, limit: int | None = None) -> list[dict]:
    """Per (trial, response, seed): the trial-dir artifacts the Phase-5/6
    pipeline already wrote — snapshot.png, the response's audit-fit PNG, and
    measured.json. Never raises on missing files: an in-flight sim's dir holds
    only post/ + run.out and renders as a 'pending' placeholder; a recorded
    failure renders as a 'failed' badge. Trials whose hash user_attr is not
    yet set (sim still running) yield one 'running' placeholder."""
    items = []
    trials = sorted(study.get_trials(deepcopy=False),
                    key=lambda t: t.number, reverse=newest_first)
    if limit is not None:
        trials = trials[:limit]
    for t in trials:
        items.extend(_items_for_trial(t, cfg))
    return items


def tail_log(study_dir: Path, n_lines: int = 80) -> str:
    """Last n_lines of run.log, '' if absent."""
    log = Path(study_dir) / LOGFILE
    if not log.exists():
        return ""
    try:
        lines = log.read_text(errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(lines[-n_lines:])


def response_specs(cfg: "optimize.StudyConfig") -> dict:
    """Per enabled response, the merged chart/gallery spec: registry metadata
    (label, result/std keys, fit PNG) + the CONFIG's target/sigma/weight — the
    config, not the registry default, is the source of truth for the band."""
    out = {}
    for name in cfg.enabled_responses():
        calib = runner.RESPONSES[name]["calib"]
        rc = cfg.responses[name]
        out[name] = {
            "label": calib["label"],
            "result_key": calib["result_key"],
            "std_key": calib["std_key"],
            "fit_png": calib["fit_png"],
            "target": rc["target"],
            "sigma": rc["sigma"],
            "weight": rc["weight"],
        }
    return out


def family_anchors() -> list[dict]:
    """The shipped material card's equivalence-family anchors (the documented
    valley ridge), for overlay on the live valley chart. [] when the card is
    absent or unparseable — the overlay is decoration, never a failure."""
    card = REPO_ROOT / "materials" / "wheat.json"
    try:
        payload = json.loads(card.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    anchors = (payload.get("equivalence_family") or {}).get("anchors") or []
    return [a for a in anchors
            if isinstance(a, dict) and "fric" in a and "rollfric" in a]


CACHE_HIT_S = 5.0   # a completed trial faster than this never ran a sim


def trial_spans(study) -> list[dict]:
    """Wall-clock span per trial from the study's datetime_start/complete:
    {'trial', 'state', 'start', 'end', 'duration_s', 'cached'}. Running trials
    carry end=None (the chart draws them to now). Trials execute sequentially
    (study.optimize parallelism lives INSIDE a trial), so spans tile the run."""
    spans = []
    for t in study.get_trials(deepcopy=False):
        start, end = t.datetime_start, t.datetime_complete
        dur = (end - start).total_seconds() if (start and end) else None
        spans.append({"trial": t.number, "state": t.state.name.lower(),
                      "start": start, "end": end, "duration_s": dur,
                      "cached": dur is not None and dur < CACHE_HIT_S})
    spans.sort(key=lambda s: s["trial"])
    return spans


def _human_s(sec: float) -> str:
    if sec < 90:
        return f"{sec:.0f} s"
    if sec < 5400:
        return f"{sec / 60:.0f} m"
    return f"{sec / 3600:.1f} h"


def eta(study_dir: Path, spans: list[dict], cfg: "optimize.StudyConfig") -> dict:
    """Live ETA for the current run: median LIVE (non-cached) completed-trial
    duration x trials remaining in this invocation (study.optimize runs
    cfg.trials NEW trials per run/resume). Honest because trials are strictly
    sequential. {'running', 'eta_s', 'text', 'remaining', 'low_confidence'}."""
    out = {"running": False, "eta_s": None, "text": None,
           "remaining": None, "low_confidence": False}
    status = run_status(study_dir)
    if not status["running"] or not status.get("started"):
        return out
    out["running"] = True
    try:
        started = datetime.fromisoformat(status["started"])
        # the pidfile timestamp is aware UTC; optuna datetimes are naive local
        started_local = started.astimezone().replace(tzinfo=None)
    except ValueError:
        started_local = None

    completed = [s for s in spans if s["state"] == "complete"]
    done_this_run = [s for s in completed
                     if started_local is None
                     or (s["start"] and s["start"] >= started_local)]
    out["remaining"] = max(cfg.trials - len(done_this_run), 0)

    live = sorted(s["duration_s"] for s in completed
                  if s["duration_s"] is not None and not s["cached"])
    if not live:    # all-cached study (e.g. a warm-start replay): weak signal
        live = sorted(s["duration_s"] for s in completed
                      if s["duration_s"] is not None)
        out["low_confidence"] = True
    if not live:
        out["text"] = "estimating…"
        return out
    median_s = live[len(live) // 2]
    out["eta_s"] = out["remaining"] * median_s
    out["text"] = (f"≈ {_human_s(out['eta_s'])} "
                   f"({out['remaining']} × ~{_human_s(median_s)})"
                   + (" · low confidence" if out["low_confidence"] else ""))
    return out


def trial_detail(study, cfg: "optimize.StudyConfig", trial_number: int) -> dict | None:
    """Everything the trial-detail dialog shows for one trial: params, loss,
    per-response values vs band, the trial's gallery items (with seed dirs for
    the 3-D viewer / video buttons), and the cache dirs per response."""
    import optuna

    t = next((x for x in study.get_trials(deepcopy=False)
              if x.number == trial_number), None)
    if t is None:
        return None
    detail = {
        "trial": t.number,
        "state": t.state.name.lower(),
        "loss": t.value if t.state == optuna.trial.TrialState.COMPLETE else None,
        "params": {d: t.params.get(d) for d in optimize.DIMS},
        "responses": {},
        "dirs": {},
        "items": _items_for_trial(t, cfg),
    }
    for r in cfg.enabled_responses():
        calib = runner.RESPONSES[r]["calib"]
        rc = cfg.responses[r]
        detail["responses"][r] = {
            "label": calib["label"],
            "value": t.user_attrs.get(calib["result_key"]),
            "std": t.user_attrs.get(calib["std_key"]),
            "target": rc["target"], "sigma": rc["sigma"],
        }
        h = t.user_attrs.get(optimize._hash_attr(r))
        if h:
            detail["dirs"][r] = runner.CACHE / f"{runner.RESPONSES[r]['dir_prefix']}{h}"
    return detail


def parse_psd_csv(data: bytes) -> list[list[float]]:
    """Parse an uploaded PSD CSV into [[diameter_mm, mass_frac], ...].

    Accepts named columns (anything containing diam/d_mm/size + frac/mass/
    weight/pct) or, failing that, the first two numeric columns. Percent-style
    fractions (sum ≈ 100) are rescaled; fractions are normalized to 1. The
    full physical validation happens later in runner.material_canon."""
    import io

    import pandas as pd

    df = pd.read_csv(io.BytesIO(data))
    if df.empty:
        raise ValueError("the CSV has no rows")

    def _find(needles):
        for c in df.columns:
            if any(n in str(c).strip().lower() for n in needles):
                return c
        return None

    d_col = _find(("diam", "d_mm", "size"))
    w_col = _find(("frac", "mass", "weight", "pct", "%"))
    if d_col is None or w_col is None or d_col == w_col:
        numeric = df.select_dtypes("number").columns
        if len(numeric) < 2:
            raise ValueError("need two numeric columns: diameter_mm, mass_fraction")
        d_col, w_col = numeric[0], numeric[1]

    pairs = (df[[d_col, w_col]].apply(pd.to_numeric, errors="coerce")
             .dropna().values.tolist())
    pairs = [[float(d), float(w)] for d, w in pairs if w > 0]
    if not pairs:
        raise ValueError("no usable (diameter, fraction) rows in the CSV")
    total = sum(w for _, w in pairs)
    return [[float(f"{d:.6g}"), float(f"{w / total:.6g}")]
            for d, w in sorted(pairs)]


def dump_points(trial_dir: Path, *, max_points: int = 6000) -> dict:
    """Final-dump particle positions for the in-browser 3-D viewer:
    {'df' (x/y/z/radius DataFrame), 'n_total', 'n_shown', 'dump'}. Stride-
    downsampled above max_points (4k-particle heaps pass through untouched).
    Pure file parsing (measure.read_dump) — no OVITO anywhere near this."""
    from calibration import measure, render

    dump = render.find_final_dump(trial_dir)
    df = measure.read_dump(dump)
    n_total = len(df)
    if n_total > max_points:
        df = df.iloc[::(n_total // max_points) + 1]
    return {"df": df, "n_total": n_total, "n_shown": len(df), "dump": dump}


# ------------------------------------------------------------- video layer
# Launch + watch the video.py subprocesses. Same charter as start_run: the
# Streamlit process must never call OVITO (not thread-safe off the main
# thread), so renders are detached CLI children and the <out>.progress.json
# sidecar is the only coupling.

def _seed_sidecar(out: Path, pid: int, match: str) -> None:
    """Write the initial progress sidecar from the PARENT so the UI reads
    'running' immediately; the child overwrites it on every stage change."""
    payload = {"pid": pid, "match": match, "out": str(out), "stage": "spawned",
               "frame": 0, "n_frames": 0, "error": None,
               "started": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "updated": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    pp = video.progress_path(out)
    tmp = pp.with_name(pp.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    tmp.rename(pp)


def _progress_state(prog_path: Path, artifact: Path | None) -> dict:
    """Sidecar + artifact -> {'state': none|running|done|error, 'path',
    'frame', 'n_frames', 'stage', 'error'}. A dead pid mid-stage reads as an
    interrupted render, not a phantom 'running' (same argv-matching guard as
    run_status — macOS ps rewrites argv[0])."""
    out = {"state": "none", "path": artifact, "frame": 0, "n_frames": 0,
           "stage": None, "error": None}
    raw = None
    if prog_path.exists():
        try:
            raw = json.loads(prog_path.read_text())
        except (json.JSONDecodeError, OSError):
            raw = None
    if raw is None:
        if artifact is not None:
            out["state"] = "done"
        return out
    out.update({"frame": raw.get("frame") or 0,
                "n_frames": raw.get("n_frames") or 0,
                "stage": raw.get("stage"), "error": raw.get("error")})
    stage = raw.get("stage")
    if stage == "done":
        out["state"] = "done"
        produced = Path(raw["out"]) if raw.get("out") else None
        out["path"] = produced if (produced and produced.exists()) else artifact
        return out
    if stage == "error":
        out["state"] = "error"
        return out
    pid, match = raw.get("pid"), raw.get("match", "video.py")
    alive = False
    if pid:
        try:
            os.kill(int(pid), 0)
            alive = match in _cmdline(int(pid))
        except (ProcessLookupError, PermissionError, ValueError):
            alive = False
    if alive:
        out["state"] = "running"
    else:
        out["state"] = "error"
        out["error"] = out["error"] or "render interrupted (process gone)"
    return out


def _spawn_detached(argv: list[str], log_path: Path) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = open(log_path, "ab")  # noqa: SIM115 — handle passes to the child
    try:
        proc = subprocess.Popen(argv, cwd=REPO_ROOT, stdin=subprocess.DEVNULL,
                                stdout=log, stderr=subprocess.STDOUT,
                                start_new_session=True)
    finally:
        log.close()
    return proc.pid


def video_path(trial_dir: Path, kind: str) -> Path | None:
    """The rendered artifact if it exists (.mp4, or the .gif fallback)."""
    mp4 = Path(trial_dir) / f"video_{kind}.mp4"
    for p in (mp4, mp4.with_suffix(".gif")):
        if p.exists():
            return p
    return None


def video_status(trial_dir: Path, kind: str) -> dict:
    mp4 = Path(trial_dir) / f"video_{kind}.mp4"
    return _progress_state(video.progress_path(mp4), video_path(trial_dir, kind))


def start_video(trial_dir: Path, kind: str, response: str | None = None, *,
                argv: list[str] | None = None) -> dict:
    """Detached `video.py movie` for one trial dir. Refuses while that kind is
    already rendering. argv override = tests only (a sleeper, not a render)."""
    trial_dir = Path(trial_dir)
    if video_status(trial_dir, kind)["state"] == "running":
        raise RuntimeError(f"a {kind} render is already running for {trial_dir.name}")
    out = trial_dir / f"video_{kind}.mp4"
    if argv is None:
        argv = [str(PYTHON), str(VIDEO_PY), "movie", str(trial_dir),
                "--kind", kind]
        if response:
            argv += ["--response", response]
        match = video.movie_match(trial_dir)
    else:
        match = " ".join(argv[1:]) if len(argv) > 1 else argv[0]
    pid = _spawn_detached(argv, trial_dir / VIDEO_LOG)
    _seed_sidecar(out, pid, match)
    return {"pid": pid, "out": str(out), "kind": kind}


def hero_paths(cfg: "optimize.StudyConfig") -> dict:
    """{response: artifact path} for the study's existing hero videos."""
    out = {}
    for r in cfg.enabled_responses():
        mp4 = Path(cfg.outdir) / f"hero_{r}.mp4"
        found = next((p for p in (mp4, mp4.with_suffix(".gif")) if p.exists()), None)
        if found:
            out[r] = found
    return out


def hero_status(study_dir: Path) -> dict:
    return _progress_state(video.progress_path(Path(study_dir) / "hero.mp4"), None)


def start_hero(study_dir: Path, *, force: bool = False,
               argv: list[str] | None = None) -> dict:
    """Detached `video.py hero --config …` for a study (the manual path for
    studies finished before the end-of-run hook existed, or after Stop)."""
    study_dir = Path(study_dir)
    if hero_status(study_dir)["state"] == "running":
        raise RuntimeError("a hero render is already running for this study")
    config = study_dir / "config.json"
    if argv is None:
        if not config.exists():
            raise FileNotFoundError(f"no config.json in {study_dir}")
        argv = [str(PYTHON), str(VIDEO_PY), "hero", "--config", str(config)]
        if force:
            argv.append("--force")
        match = video.hero_match(config)
    else:
        match = " ".join(argv[1:]) if len(argv) > 1 else argv[0]
    pid = _spawn_detached(argv, study_dir / VIDEO_LOG)
    _seed_sidecar(study_dir / "hero.mp4", pid, match)
    return {"pid": pid, "study": str(study_dir)}


def material_card_preview(best_payload: dict) -> dict:
    """A material-card-shaped preview of a best.json payload — what
    material_card.py build would start from. Pure formatting: clones the
    engine/contact-model boilerplate from the shipped wheat card when present,
    and is explicitly NOT written to materials/ (preview only — building a
    real card stays a deliberate CLI act)."""
    best = best_payload.get("best") or {}
    card = {"_preview": "NOT a deliverable — material_card.py build is the real path"}
    shipped = REPO_ROOT / "materials" / "wheat.json"
    if shipped.exists():
        try:
            ref = json.loads(shipped.read_text())
            card["engine"] = ref.get("engine")
            card["contact_model"] = ref.get("contact_model")
            card["fixed_inputs"] = ref.get("fixed_inputs")
        except (json.JSONDecodeError, OSError):
            pass
    mat = best_payload.get("material")
    if mat:    # the study ran a custom material — ITS inputs are the fixed ones
        card["fixed_inputs"] = {
            "material_name": mat.get("name"),
            "particle_density_kgm3": mat.get("particle_density_kgm3"),
            "psd_mm": {f"{d:g} mm": w for d, w in mat.get("psd_mm", [])},
            "youngs_modulus_pa": mat.get("youngs_modulus_pa"),
            "timestep_s": mat.get("timestep_s") or "auto (Rayleigh-scaled)",
            "n_particles_heap": mat.get("n_particles"),
        }
    card["parameters"] = {
        k: {"value": v, "role": "calibrated"}
        for k, v in (best.get("params") or {}).items()}
    card["responses"] = {}
    for name, tgt in (best_payload.get("targets") or {}).items():
        calib = runner.RESPONSES.get(name, {}).get("calib", {})
        key = calib.get("result_key", name)
        card["responses"][name] = {
            "value": best.get(key),
            "std": best.get(calib.get("std_key", f"{key}_std")),
            "target": tgt.get("target"), "target_sigma": tgt.get("sigma"),
        }
    if best.get("bulk_density") is not None:
        card["responses"]["bulk_density"] = {
            "value": best.get("bulk_density"), "calibrated": False}
    card["target_met"] = best_payload.get("target_met")
    card["evidence"] = {"trial_dir": best.get("trial_dir"),
                        "study_name": best_payload.get("study_name"),
                        "n_trials": best_payload.get("n_trials")}
    return card
