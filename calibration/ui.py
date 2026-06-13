"""Calibration cockpit (Phase 8.5) — configure → start → watch live → results.

    .venv/bin/streamlit run calibration/ui.py

A thin Streamlit view over the existing pipeline: it owns no calibration
logic and invents no state. Configure writes a config.json via
optimize.save_config — the same file the bare CLI accepts (`optimize.py run
--config …`), so the browser is never the source of truth. Start/Stop manage
an optimize.py subprocess through ui_state's pidfile (survives page reloads
by construction: every render re-derives from pidfile + SQLite + trial dirs).
The live view polls the study read-only — the concurrent-SQLite pattern
optuna-dashboard already proves safe — and the gallery surfaces the
snapshot/fit artifacts every trial dir has carried since Phase 5/6.

Premium layer (2026-06): dark mission-control theme (ui_theme), interactive
plotly charts incl. the valley map with the equivalence-family overlay
(ui_charts), filterable gallery cards with a trial-detail dialog (full-res
images, measured.json, an in-browser 3-D particle viewer over the kept final
dump), trial timeline + live ETA, on-demand per-trial videos and end-of-run
hero videos (video.py, always a detached subprocess — OVITO is not
thread-safe off the main thread), and a one-click self-contained report.html
(report.py). None of it adds state: every pixel re-derives from config.json +
study.db + trial dirs + sidecar files.

optuna-dashboard stays wired as the always-working fallback (sidebar).
"""

import json
import sys
from pathlib import Path

import streamlit as st

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from calibration import optimize, runner, ui_charts, ui_state, ui_theme, video  # noqa: E402

st.set_page_config(page_title="DEM calibration", page_icon="🌾", layout="wide")
st.markdown(f"<style>{ui_theme.CSS}</style>", unsafe_allow_html=True)

POLL_S = 5          # status/gallery/chart poll; trials land every ~4 min — plenty


# ------------------------------------------------------------- helpers

def _calibratable() -> dict:
    """Response registry entries the UI may offer (those carrying calib
    metadata). Holdouts are shown but disabled — visible honesty beats
    silent omission."""
    return {name: spec for name, spec in runner.RESPONSES.items() if "calib" in spec}


def _replay_cmd(config_path: Path) -> str:
    rel = optimize._repo_rel(config_path)   # repo-relative when possible
    return f".venv/bin/python calibration/optimize.py run --config '{rel}'"


def _load_best(cfg) -> dict | None:
    if not cfg.best_json.exists():
        return None
    try:
        return json.loads(cfg.best_json.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _open_trial_from_selection(event, key: str) -> None:
    """Click-to-inspect: a chart point selection (customdata = trial number)
    opens that trial's dialog. Selections are sticky across reruns, so the
    last-handled trial is remembered per chart — the dialog opens once per
    click, not once per poll."""
    points = getattr(getattr(event, "selection", None), "points", None) or []
    if not points:
        st.session_state.pop(f"_sel_{key}", None)
        return
    cd = points[0].get("customdata")
    if isinstance(cd, (list, tuple)):
        cd = cd[0] if cd else None
    if cd is None:
        return
    trial = int(cd)
    if st.session_state.get(f"_sel_{key}") == trial:
        return
    st.session_state[f"_sel_{key}"] = trial
    st.session_state["dialog_trial"] = trial
    st.rerun(scope="app")


_STATUS_PILL = {"ok": "ok", "failed": "err", "pending": "pending",
                "running": "run"}


@st.cache_data(ttl=600, show_spinner="parsing dump…")
def _dump_points_cached(trial_dir: str) -> dict:
    """Trial dirs are immutable once pruned, so the path alone is the key."""
    return ui_state.dump_points(Path(trial_dir))


def _measured_table(measured: dict) -> list[dict]:
    """measured.json flattened to displayable key/value rows (params and the
    long frame_angles series get their own UI treatments)."""
    rows = []
    for k, v in measured.items():
        if k in ("params", "frame_angles") or isinstance(v, dict):
            continue
        if isinstance(v, list):
            v = ", ".join(str(x) for x in v) or "—"
        rows.append({"key": k, "value": v})
    return rows


_KIND_BLURB = {
    "turntable": "360° orbit of the final heap (~2 min render)",
    "formation": "full pour-settle-lift sequence — re-simulates this trial "
                 "(~5 min total), cache untouched",
    "flow": "steady-state avalanching from the kept drum frames (~1–2 min)",
}


def _show_video(path: Path, caption: str | None = None) -> None:
    if path.suffix == ".gif":
        st.image(str(path), caption=caption)
    else:
        st.video(str(path))
        if caption:
            st.caption(caption)


def _video_cell(item: dict, kind: str) -> None:
    """One video slot in the trial dialog: player when done, progress while
    rendering, a launch button otherwise (formation behind a confirm popover
    because it re-simulates). Widget keys carry trial/response/seed/kind so
    multiple dialogs' states never collide."""
    status = ui_state.video_status(item["trial_dir"], kind)
    key = f"vid_{item['trial']}_{item['response']}_{item['seed']}_{kind}"
    if status["state"] == "done" and status["path"]:
        _show_video(Path(status["path"]), caption=kind)
        return
    if status["state"] == "running":
        total = status["n_frames"] or 0
        if status["stage"] == "simulate":
            st.progress(0.05, text=f"{kind}: re-simulating (~4 min)…")
        elif total:
            st.progress(min(status["frame"] / total, 1.0),
                        text=f"{kind}: frame {status['frame']}/{total}")
        else:
            st.progress(0.02, text=f"{kind}: starting…")
        st.button("Refresh", key=f"{key}_poll", icon=":material/refresh:")
        return
    if status["state"] == "error":
        st.caption(f"{kind}: last render failed — {status['error']}")
    if kind == "formation":
        with st.popover("Render formation…", icon=":material/movie:"):
            st.caption(_KIND_BLURB[kind])
            if st.button("Re-simulate + render", key=key, type="primary"):
                try:
                    ui_state.start_video(item["trial_dir"], kind, item["response"])
                except RuntimeError as err:
                    st.warning(str(err))
                st.rerun(scope="fragment")
    else:
        if st.button(f"Render {kind}", key=key, icon=":material/movie:",
                     help=_KIND_BLURB[kind]):
            try:
                ui_state.start_video(item["trial_dir"], kind, item["response"])
            except RuntimeError as err:
                st.warning(str(err))
            st.rerun(scope="fragment")


@st.dialog("Trial detail", width="large")
def trial_dialog(detail: dict) -> None:
    loss = detail.get("loss")
    kind = ("ok" if loss is not None and loss <= 1.0
            else "warn" if loss is not None else "pending")
    st.markdown(
        f"### Trial {detail['trial']} &nbsp;"
        + ui_theme.pill(kind, f"loss {loss:.3f}σ" if loss is not None
                        else detail["state"]),
        unsafe_allow_html=True)
    st.caption(" · ".join(f"{k} **{v:.4f}**" for k, v in detail["params"].items()
                          if v is not None))
    chips = []
    for name, r in detail["responses"].items():
        if r["value"] is None:
            chips.append(ui_theme.pill("idle", f"{name} —"))
            continue
        in_band = abs(r["value"] - r["target"]) <= r["sigma"]
        chips.append(ui_theme.pill("ok" if in_band else "err",
                                   f"{name} {r['value']:.2f}"))
    st.markdown(" ".join(chips), unsafe_allow_html=True)

    items = [i for i in detail["items"] if i.get("trial_dir")]
    tab_img, tab_meas, tab_3d = st.tabs(
        [":material/image: Images", ":material/table_chart: Measured",
         ":material/view_in_ar: 3D view"])

    with tab_img:
        if not items:
            st.info("No artifacts on disk yet for this trial.")
        for item in items:
            st.markdown(f"**{item['response']}** · seed {item['seed']} "
                        + ui_theme.pill(_STATUS_PILL[item["status"]], item["status"]),
                        unsafe_allow_html=True)
            c1, c2 = st.columns(2)
            if item["snapshot"]:
                c1.image(str(item["snapshot"]), caption="snapshot")
            if item["fit"]:
                c2.image(str(item["fit"]), caption="measurement audit")

    with tab_meas:
        for item in items:
            if not item.get("measured"):
                continue
            st.markdown(f"**{item['response']}** · seed {item['seed']}")
            st.dataframe(_measured_table(item["measured"]),
                         width="stretch", height=240, hide_index=True)
            angles = item["measured"].get("frame_angles")
            if angles:
                st.line_chart(angles, height=120)
                st.caption("per-frame dynamic AoR across the steady window "
                           "(the avalanche cycle)")

    with tab_3d:
        dirs = [i for i in items if i["snapshot"] or i["status"] == "ok"]
        if not dirs:
            st.info("No final dump available yet.")
        else:
            labels = {f"{i['response']} · seed {i['seed']}": i for i in dirs}
            pick = st.selectbox("simulation", list(labels), key="d3_pick")
            color_by = st.segmented_control("color by", ["z", "radius"],
                                            default="z", key="d3_color")
            try:
                pts = _dump_points_cached(str(labels[pick]["trial_dir"]))
            except (FileNotFoundError, OSError, ValueError) as err:
                st.warning(f"could not parse the dump: {err}")
            else:
                st.plotly_chart(
                    ui_charts.dump_scatter3d_figure(pts["df"],
                                                    color_by=color_by or "z"),
                    key="chart_3d", theme=None)
                st.caption(f"{pts['n_shown']} of {pts['n_total']} particles · "
                           "drag to rotate, scroll to zoom — marker size is "
                           "screen-mapped; true radius in hover")

    ok_items = [i for i in items if i["status"] == "ok"]
    if ok_items:
        st.divider()
        st.markdown("**Videos** — rendered headless by a detached `video.py` "
                    "subprocess; any click in this dialog refreshes status")
        for item in ok_items:
            kinds = video.KINDS_BY_RESPONSE.get(item["response"], ())
            if not kinds:
                continue
            st.markdown(f"*{item['response']} · seed {item['seed']}*")
            for col, kind in zip(st.columns(max(len(kinds), 2)), kinds):
                with col:
                    _video_cell(item, kind)


# ------------------------------------------------------------- sidebar

st.sidebar.title("🌾 DEM calibration")
studies = ui_state.list_studies()
names = [s["name"] for s in studies]

new_name = st.sidebar.text_input("New study name", placeholder="e.g. wheat-drawdown-v1")
if st.sidebar.button("Create study", disabled=not new_name):
    target = ui_state.study_dir(new_name.strip())
    if (target / "config.json").exists():
        st.sidebar.error(f"study '{new_name}' already exists")
    else:
        cfg0 = optimize.default_config()
        cfg1 = optimize.StudyConfig(
            study_name=new_name.strip(), outdir=target,
            responses=cfg0.responses, search_bounds=cfg0.search_bounds,
            sampler=cfg0.sampler, sampler_seed=cfg0.sampler_seed,
            n_seeds=cfg0.n_seeds, trials=cfg0.trials, jobs=cfg0.jobs,
            seed_csv=cfg0.seed_csv, density=cfg0.density,
            fail_penalty=cfg0.fail_penalty)
        optimize.save_config(cfg1, target / "config.json")
        st.rerun()

if not names:
    st.sidebar.info("No studies yet — create one above.")
    st.title("Calibration cockpit")
    st.markdown("Create a study in the sidebar to begin. Each study is a "
                "directory under `results/studies/<name>/` whose `config.json` "
                "is also accepted by the bare CLI — nothing here exists only "
                "in the browser.")
    st.stop()

selected = st.sidebar.selectbox("Study", names)
entry = next(s for s in studies if s["name"] == selected)
sdir = entry["dir"]
cfg = entry["cfg"]
status = ui_state.run_status(sdir)

if entry["error"]:
    st.sidebar.error(f"config.json invalid: {entry['error']}")
    st.error(f"`{sdir / 'config.json'}` failed validation: {entry['error']}\n\n"
             "Fix the file by hand or recreate the study.")
    st.stop()

st.sidebar.markdown(
    ui_theme.pill("run", f"running · since {status['started']}") if status["running"]
    else (ui_theme.pill("ok", "finished · best.json present")
          if cfg.best_json.exists() else ui_theme.pill("idle", "idle")),
    unsafe_allow_html=True)

with st.sidebar.expander("optuna-dashboard fallback"):
    st.code(f".venv/bin/python calibration/optimize.py dashboard "
            f"--config '{optimize._repo_rel(sdir / 'config.json')}'",
            language="bash")

tab_cfg, tab_run, tab_results = st.tabs(
    [":material/tune: Configure", ":material/rocket_launch: Run",
     ":material/leaderboard: Results"])


# ------------------------------------------------------------- configure

with tab_cfg:
    st.subheader(f"Configure — {selected}")
    if status["running"]:
        st.warning("A run is live — stop it before editing the configuration.")

    # ---- material: PSD upload lives OUTSIDE the form so a parsed file
    # pre-fills the editor immediately (form widgets only apply on submit)
    mat_saved = cfg.material or dict(runner.WHEAT_MATERIAL)
    upload = st.file_uploader(
        "Upload a particle-size distribution (CSV: diameter_mm, mass_fraction "
        "— percent columns accepted)", type=["csv"], key="psd_csv",
        disabled=status["running"])
    psd_upload = None
    if upload is not None:
        try:
            psd_upload = ui_state.parse_psd_csv(upload.getvalue())
            st.caption(f"parsed **{len(psd_upload)} bins** — review below, "
                       "then Save config.json")
        except ValueError as err:
            st.error(f"PSD CSV: {err}")

    with st.form("config", border=False):
        st.markdown("**Material** — the measured physical inputs (never "
                    "calibrated). A non-default material simulates in its own "
                    "cache namespace; the built-in wheat keeps reusing the "
                    "existing cache.")
        mcols = st.columns([2, 1, 1, 1])
        mat_name = mcols[0].text_input(
            "material name", value=str(mat_saved["name"]),
            disabled=status["running"])
        rho_in = mcols[1].number_input(
            "particle density [kg/m³]", min_value=100.0, max_value=20000.0,
            value=float(mat_saved["particle_density_kgm3"]), step=10.0,
            disabled=status["running"])
        ymod_in = mcols[2].number_input(
            "Young's modulus [Pa]", min_value=1.0e5, max_value=1.0e9,
            value=float(mat_saved["youngs_modulus_pa"]), format="%.1e",
            disabled=status["running"],
            help="softened numerical stiffness (standard DEM practice) — "
                 "real stiffness only shrinks the timestep")
        npart_in = mcols[3].number_input(
            "heap particles", min_value=100, max_value=50000,
            value=int(mat_saved["n_particles"]), step=100,
            disabled=status["running"],
            help="drum tests auto-scale their count to keep the published "
                 "50% fill")

        import pandas as pd
        psd_df = pd.DataFrame(psd_upload or mat_saved["psd_mm"],
                              columns=["diameter_mm", "mass_fraction"])
        pcol, dtcol = st.columns([3, 2])
        edited_psd = pcol.data_editor(
            psd_df, num_rows="dynamic", key="psd_editor", width="stretch",
            disabled=status["running"],
            column_config={
                "diameter_mm": st.column_config.NumberColumn(
                    "diameter [mm]", min_value=0.5, max_value=20.0,
                    step=0.05, format="%.2f"),
                "mass_fraction": st.column_config.NumberColumn(
                    "mass fraction", min_value=0.0, max_value=1.0,
                    step=0.01, format="%.3f",
                    help="normalized on save — percentages are fine"),
            })
        with dtcol:
            dt_auto_flag = st.checkbox(
                "auto timestep (Rayleigh-scaled)",
                value=mat_saved["timestep_s"] is None,
                disabled=status["running"],
                help="τ_R ∝ r·√(ρ/G), anchored to the validated wheat 8e-6 s; "
                     "the in-template check/timestep/gran guard re-verifies "
                     "at run time")
            dt_in = st.number_input(
                "timestep [s] (ignored while auto)", min_value=1.0e-7,
                max_value=5.0e-5,
                value=float(mat_saved["timestep_s"]
                            or runner.dt_auto(mat_saved["psd_mm"],
                                              float(mat_saved["particle_density_kgm3"]),
                                              float(mat_saved["youngs_modulus_pa"]))),
                format="%.2e", disabled=status["running"])
            _mat_chk = runner.material_canon(cfg.material)
            if _mat_chk is not None:
                _factor = ((runner._npart_for("aor", _mat_chk) / 4000)
                           * (runner.DT_WHEAT / _mat_chk["dt"]))
                st.caption(f"≈ {4.0 * max(_factor, 0.05):.1f} min per heap sim "
                           f"at dt {_mat_chk['dt']:.2g} s (wheat ≈ 4 min)")
                _cap = runner.heap_capacity(cfg.material)
                if _mat_chk["npart"] > _cap:
                    st.warning(f"only ≈ {_cap} particles of this size fit the "
                               f"heap insertion region — LIGGGHTS will insert "
                               f"fewer than the requested {_mat_chk['npart']} "
                               "and measure a smaller (noisier) heap")
                else:
                    st.caption(f"insertion-region capacity ≈ {_cap} particles")

        st.markdown("**Responses** (targets ± σ from the experiments docs; "
                    "weights are σ-normalized so 1:1 = equal evidence)")
        resp_widgets = {}
        for name, spec in _calibratable().items():
            calib = spec["calib"]
            current = cfg.responses.get(name, {
                "enabled": False, "target": calib["target"],
                "sigma": calib["sigma"], "weight": calib["weight"]})
            cols = st.columns([2, 1, 1, 1])
            enabled = cols[0].checkbox(
                calib["label"], value=current["enabled"] and not calib["holdout"],
                disabled=calib["holdout"] or status["running"],
                help=("Phase-10 hold-out — calibrating against it would destroy "
                      "the validation. Not selectable." if calib["holdout"] else None),
                key=f"en_{name}")
            target = cols[1].number_input(
                "target", value=float(current["target"]), step=0.1, format="%.2f",
                disabled=calib["holdout"] or status["running"], key=f"tg_{name}")
            sigma = cols[2].number_input(
                "σ", value=float(current["sigma"]), min_value=0.01, step=0.1,
                format="%.2f", disabled=calib["holdout"] or status["running"],
                key=f"sg_{name}")
            weight = cols[3].number_input(
                "weight", value=float(current["weight"]), min_value=0.0, step=0.1,
                disabled=calib["holdout"] or status["running"], key=f"wt_{name}")
            resp_widgets[name] = {"enabled": enabled, "target": target,
                                  "sigma": sigma, "weight": weight,
                                  "holdout": calib["holdout"]}

        st.markdown("**Search bounds** (clamped to the physical "
                    "`runner.RANGES`; defaults = Phase-9 box)")
        bounds = {}
        bcols = st.columns(len(optimize.DIMS))
        for col, d in zip(bcols, optimize.DIMS):
            rlo, rhi = runner.RANGES[d]
            lo, hi = cfg.search_bounds[d]
            bounds[d] = col.slider(d, min_value=float(rlo), max_value=float(rhi),
                                   value=(float(lo), float(hi)), step=0.01,
                                   disabled=status["running"])

        st.markdown("**Optimizer**")
        ocols = st.columns(5)
        sampler = ocols[0].selectbox("sampler", ["gp", "tpe"],
                                     index=["gp", "tpe"].index(cfg.sampler),
                                     disabled=status["running"])
        sampler_seed = ocols[1].number_input("sampler seed", value=cfg.sampler_seed,
                                             step=1, disabled=status["running"])
        n_seeds = ocols[2].number_input("seeds/candidate", value=cfg.n_seeds,
                                        min_value=1, max_value=len(runner.SEEDS),
                                        step=1, disabled=status["running"])
        trials = ocols[3].number_input("trials", value=cfg.trials, min_value=1,
                                       step=1, disabled=status["running"])
        jobs = ocols[4].number_input("jobs (0 = auto)", value=cfg.jobs or 0,
                                     min_value=0, step=1, disabled=status["running"])

        seed_valley = st.checkbox(
            "Warm-start from the M4 valley-check anchors "
            "(wheat-cache hits — free for the default material only)",
            value=cfg.seed_csv is not None and cfg.material is None,
            disabled=status["running"] or cfg.material is not None,
            help=("Disabled: the anchors are cached WHEAT simulations — with a "
                  "custom material each would re-simulate from scratch."
                  if cfg.material is not None else None))

        submitted = st.form_submit_button("Save config.json", icon=":material/save:",
                                          disabled=status["running"])

    if submitted:
        psd_list = [[float(r["diameter_mm"]), float(r["mass_fraction"])]
                    for _, r in edited_psd.iterrows()
                    if pd.notna(r["diameter_mm"]) and pd.notna(r["mass_fraction"])
                    and r["mass_fraction"] > 0]
        material_in = {
            "name": mat_name.strip() or "custom",
            "particle_density_kgm3": float(rho_in),
            "psd_mm": psd_list,
            "youngs_modulus_pa": float(ymod_in),
            "timestep_s": None if dt_auto_flag else float(dt_in),
            "n_particles": int(npart_in),
        }
        try:        # physical validation; default-equivalent collapses to None
            material = None if runner.material_canon(material_in) is None else material_in
        except ValueError as err:
            st.error(f"material: {err}")
            material = cfg.material            # keep the last valid one
            st.stop()
        if material is not None and seed_valley:
            st.info("custom material — valley warm-start dropped (those anchors "
                    "are wheat-cache hits and would re-simulate)")
        new_cfg = optimize.StudyConfig(
            study_name=cfg.study_name, outdir=sdir,
            responses={name: {"enabled": w["enabled"] and not w["holdout"],
                              "target": w["target"], "sigma": w["sigma"],
                              "weight": w["weight"]}
                       for name, w in resp_widgets.items()},
            search_bounds={d: tuple(v) for d, v in bounds.items()},
            sampler=sampler, sampler_seed=int(sampler_seed),
            n_seeds=int(n_seeds), trials=int(trials),
            jobs=int(jobs) or None,
            seed_csv=(optimize.default_config().seed_csv
                      if seed_valley and material is None else None),
            density=cfg.density, fail_penalty=cfg.fail_penalty,
            material=material)
        path = optimize.save_config(new_cfg, sdir / "config.json")
        try:                                   # round-trip through the validator
            optimize.load_config(path)
        except ValueError as err:
            st.error(f"saved, but the config fails validation: {err}")
        else:
            st.success(f"wrote `{optimize._repo_rel(path)}` — the CLI replay is:")
            st.code(_replay_cmd(path), language="bash")
            st.rerun()

    if cfg.material is not None:
        st.plotly_chart(
            ui_charts.psd_figure(cfg.material["psd_mm"],
                                 name=str(cfg.material.get("name", ""))),
            key="chart_psd", theme=None)
        st.caption("PSD as saved — targets above should be re-measured for "
                   "this material (the defaults are wheat literature values)")

    st.caption("This file — not the browser session — is the study. "
               "Replaying it through the bare CLI reproduces the identical study.")


# ------------------------------------------------------------- run

with tab_run:
    st.subheader(f"Run — {selected}")
    c1, c2, c3 = st.columns(3)
    if c1.button("Start", icon=":material/play_arrow:",
                 disabled=status["running"], type="primary"):
        try:
            info = ui_state.start_run(sdir, resume=False)
            st.toast(f"started pid {info['pid']}")
        except (RuntimeError, FileNotFoundError) as err:
            st.error(str(err))
        st.rerun()
    if c2.button("Resume", icon=":material/resume:", disabled=status["running"]):
        try:
            info = ui_state.start_run(sdir, resume=True)
            st.toast(f"resumed pid {info['pid']}")
        except (RuntimeError, FileNotFoundError) as err:
            st.error(str(err))
        st.rerun()
    if c3.button("Stop", icon=":material/stop_circle:", disabled=not status["running"]):
        res = ui_state.stop_run(sdir)
        st.toast(f"stopped pid {res['pid']} (pgids {res['killed']})")
        st.rerun()
    st.caption("Stop is safe mid-trial: per-trial SQLite commits mean at most "
               "the in-flight trial is lost, and Resume (here or "
               "`optimize.py resume --config …`) re-attaches to the study.")

    @st.fragment(run_every=POLL_S)
    def status_fragment():
        s = ui_state.run_status(sdir)
        study = ui_state.load_study(cfg)
        if study is None:
            st.info("No study DB yet — press Start.")
            return
        rows = ui_state.trial_rows(study, cfg)
        done = [r for r in rows if r["state"] == "complete"]
        spans = ui_state.trial_spans(study)
        live_eta = ui_state.eta(sdir, spans, cfg)
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("state", "running" if s["running"] else "idle")
        m2.metric("trials complete", len(done))
        best = min((r["loss"] for r in done if r["loss"] is not None), default=None)
        m3.metric("best loss [σ]", f"{best:.3f}" if best is not None else "—")
        m4.metric("noise floor [σ]", f"{cfg.noise_floor():.2f}")
        m5.metric("ETA", live_eta["text"] or "—",
                  help="median live-trial duration × trials remaining "
                       "in this run (trials are sequential)")
        st.dataframe(rows[:25], width="stretch", height=240)
        log = ui_state.tail_log(sdir, 15)
        if log:
            with st.expander("run.log tail"):
                st.code(log, language="text")

    @st.fragment(run_every=POLL_S)
    def charts_fragment():
        study = ui_state.load_study(cfg)
        if study is None or not study.get_trials(deepcopy=False):
            return
        rows = ui_state.trial_rows(study, cfg)
        specs = ui_state.response_specs(cfg)
        chart_kw = dict(theme=None, on_select="rerun", selection_mode="points")

        p1, p2 = st.columns(2)
        _open_trial_from_selection(p1.plotly_chart(
            ui_charts.convergence_figure(
                rows, noise_floor=cfg.noise_floor(),
                fail_penalty=cfg.fail_penalty, specs=specs),
            key="chart_conv", **chart_kw), "chart_conv")
        _open_trial_from_selection(p2.plotly_chart(
            ui_charts.valley_figure(rows, ui_state.family_anchors(),
                                    cfg.search_bounds),
            key="chart_valley", **chart_kw), "chart_valley")

        if specs:
            for col, (name, spec) in zip(st.columns(len(specs)), specs.items()):
                _open_trial_from_selection(col.plotly_chart(
                    ui_charts.response_band_figure(rows, spec),
                    key=f"chart_band_{name}", **chart_kw), f"chart_band_{name}")

        with st.expander("Per-response loss breakdown", icon=":material/insights:"):
            st.plotly_chart(
                ui_charts.loss_breakdown_figure(rows, specs,
                                                fail_penalty=cfg.fail_penalty),
                key="chart_loss", theme=None)
        with st.expander("Trial timeline — cache hits vs live sims",
                         icon=":material/timeline:"):
            st.plotly_chart(ui_charts.timeline_figure(ui_state.trial_spans(study)),
                            key="chart_timeline", theme=None)

    @st.fragment(run_every=POLL_S)
    def gallery_fragment():
        study = ui_state.load_study(cfg)
        if study is None:
            return
        st.markdown("**Trial gallery** — every candidate as it lands; "
                    "Inspect (or click a chart point) for full detail")
        fc1, fc2, fc3 = st.columns([2, 2, 1])
        f_resp = fc1.segmented_control(
            "response", ["all", *ui_state.response_specs(cfg)],
            default="all", key="gal_resp")
        f_status = fc2.segmented_control(
            "status", ["all", "ok", "failed", "pending"],
            default="all", key="gal_status")
        sort = fc3.selectbox("sort", ["newest first", "loss ↑"], key="gal_sort")

        filtered = (f_resp not in (None, "all")) or (f_status not in (None, "all"))
        items = ui_state.gallery_items(study, cfg,
                                       limit=None if filtered else 12)
        items = [i for i in items if i["status"] != "running"]
        if f_resp not in (None, "all"):
            items = [i for i in items if i["response"] == f_resp]
        if f_status not in (None, "all"):
            items = [i for i in items if i["status"] == f_status]
        loss_by_trial = {r["trial"]: r["loss"]
                         for r in ui_state.trial_rows(study, cfg)}
        if sort == "loss ↑":
            items.sort(key=lambda i: (loss_by_trial.get(i["trial"]) is None,
                                      loss_by_trial.get(i["trial"], 1e9)))
        shown = items[:24]
        if not shown:
            st.caption("nothing matches the filter yet")
        for i in range(0, len(shown), 4):
            for col, item in zip(st.columns(4), shown[i:i + 4]):
                with col, st.container(border=True):
                    st.markdown(
                        ui_theme.pill(_STATUS_PILL[item["status"]], item["status"])
                        + f" &nbsp;**trial {item['trial']}** · {item['response']}"
                          f" · seed {item['seed']}",
                        unsafe_allow_html=True)
                    value = None
                    if item["measured"]:
                        key = runner.RESPONSES[item["response"]]["success_key"]
                        value = item["measured"].get(key)
                    loss = loss_by_trial.get(item["trial"])
                    st.caption(
                        (f"{value:.1f}° · " if value is not None else "")
                        + (f"loss {loss:.3f}σ" if loss is not None else "loss —"))
                    if item["snapshot"]:
                        st.image(str(item["snapshot"]))
                    elif item["fit"]:
                        st.image(str(item["fit"]))
                    else:
                        st.caption("no images yet")
                    if st.button("Inspect", icon=":material/search:",
                                 key=f"insp_{item['trial']}_{item['response']}"
                                     f"_{item['seed']}"):
                        st.session_state["dialog_trial"] = item["trial"]
                        st.rerun(scope="app")

    status_fragment()
    charts_fragment()
    gallery_fragment()

    _target = st.session_state.pop("dialog_trial", None)
    if _target is not None:
        _study = ui_state.load_study(cfg)
        _detail = (ui_state.trial_detail(_study, cfg, int(_target))
                   if _study else None)
        if _detail:
            trial_dialog(_detail)


# ------------------------------------------------------------- results

with tab_results:
    st.subheader(f"Results — {selected}")
    best_payload = _load_best(cfg)
    if best_payload is None:
        st.info("No best.json yet — it is written when a run finishes "
                "(or by `optimize.py plot --config …`).")
    else:
        verdict = best_payload.get("target_met")
        st.markdown(
            ui_theme.pill("ok", "all enabled responses inside their σ bands")
            if verdict else
            ui_theme.pill("warn", "best set NOT inside every σ band"),
            unsafe_allow_html=True)
        best = best_payload.get("best") or {}
        st.markdown("**Best parameter set**")
        st.table({d: [best.get("params", {}).get(d)] for d in optimize.DIMS})

        bullet_items, rows = [], []
        for name, tgt in (best_payload.get("targets") or {}).items():
            calib = runner.RESPONSES[name]["calib"]
            v = best.get(calib["result_key"])
            bullet_items.append({"label": calib["label"], "value": v,
                                 "std": best.get(calib["std_key"]),
                                 "target": tgt["target"], "sigma": tgt["sigma"]})
            rows.append({"response": name, "achieved": v,
                         "target": tgt["target"], "sigma": tgt["sigma"],
                         "in band": (v is not None
                                     and abs(v - tgt["target"]) <= tgt["sigma"])})
        if bullet_items:
            st.plotly_chart(ui_charts.target_bullet_figure(bullet_items),
                            key="chart_bullet", theme=None)
        with st.expander("Responses + top trials (tables)"):
            st.dataframe(rows, width="stretch")
            st.dataframe(best_payload.get("top") or [], width="stretch")

        st.markdown(
            ui_theme.material_card_html(
                ui_state.material_card_preview(best_payload)),
            unsafe_allow_html=True)
        with st.expander("Material-card preview as JSON — "
                         "`material_card.py build` is the deliverable path"):
            st.json(ui_state.material_card_preview(best_payload), expanded=False)

        st.markdown("**Hero videos** — the best trial in motion "
                    "(heap formation re-sim · drum steady flow)")
        heroes = ui_state.hero_paths(cfg)
        hstat = ui_state.hero_status(sdir)
        if heroes:
            for col, (resp, path) in zip(st.columns(max(len(heroes), 2)),
                                         heroes.items()):
                with col:
                    _show_video(path, caption=f"{resp} · {path.name}")
        if hstat["state"] == "running":
            total = hstat["n_frames"] or 0
            st.progress(min(hstat["frame"] / total, 1.0) if total else 0.05,
                        text=f"hero render in flight — {hstat['stage'] or 'starting'}"
                             + (f" · frame {hstat['frame']}/{total}" if total else ""))
            st.button("Refresh hero status", icon=":material/refresh:")
        elif not heroes or hstat["state"] == "error":
            if hstat["state"] == "error":
                st.caption(f"last hero render failed: {hstat['error']}")
            if st.button("Render hero videos", icon=":material/movie:",
                         help="formation for the heap (~5 min re-sim) + flow "
                              "for the drum; auto-spawned at the end of every run"):
                try:
                    ui_state.start_hero(sdir, force=hstat["state"] == "error")
                except (RuntimeError, FileNotFoundError) as err:
                    st.error(str(err))
                st.rerun()

    b1, b2 = st.columns(2)
    if b1.button("Regenerate figures (plots + search3d + best.json)",
                 icon=":material/photo_library:"):
        study = ui_state.load_study(cfg)
        if study is None:
            st.error("no study DB yet")
        else:
            figs = optimize.make_plots(study, cfg=cfg)
            figs.append(optimize.make_search3d(study, Path(cfg.outdir) / "search3d.html"))
            optimize.write_best(study, cfg=cfg)
            st.success("regenerated: " + ", ".join(p.name for p in figs))
    if b2.button("Build shareable report.html", icon=":material/description:",
                 help="one self-contained dark HTML file: verdict, material "
                      "card, interactive charts, best-trial images, hero "
                      "videos, replay command — same artifact as "
                      "`report.py --config …`"):
        from calibration import report
        with st.spinner("assembling report…"):
            report_path = report.build_report(cfg)
        st.success(f"wrote `{optimize._repo_rel(report_path)}`")
    report_file = Path(cfg.outdir) / "report.html"
    if report_file.exists():
        st.download_button(
            "Download report.html", data=report_file.read_bytes(),
            file_name=f"{cfg.study_name}-report.html", mime="text/html",
            icon=":material/download:")

    search_html = Path(cfg.outdir) / "search3d.html"
    with st.expander("3-D search view — watch the sampler walk the parameter box",
                     icon=":material/3d_rotation:", expanded=search_html.exists()):
        if search_html.exists():
            import streamlit.components.v1 as components
            components.html(search_html.read_text(), height=640, scrolling=False)
            st.caption("Press ▶ play (or scrub the slider) to replay the trials in "
                       "search order; color = AoR. Drag to rotate. Regenerate above "
                       "after more trials land — it is read-only on the study.")
        else:
            st.caption("Not generated yet — press “Regenerate figures” above "
                       "(needs at least one completed trial).")

    with st.expander("config.json (the source of truth)"):
        st.code((sdir / "config.json").read_text(), language="json")
        st.code(_replay_cmd(sdir / "config.json"), language="bash")
