"""Single-file HTML calibration report (Phase 8.5 premium).

One self-contained report.html per study — the "send it to a colleague"
deliverable: verdict, summary metrics, the material-card preview, the same
interactive plotly figures the cockpit shows (built by ui_charts, so UI and
report can never drift), best-trial snapshots, the hero videos, the shipped
card's hold-out validation, and the exact CLI replay command.

Read-only over the study artifacts (config.json + study.db + best.json +
trial dirs + hero_*.mp4). Charts load plotly.js from the CDN (same policy as
search3d.html — ~100 KB file instead of ~5 MB); images embed as base64
thumbnails; videos embed as base64 data URIs up to --max-video-mb, above
that they are referenced as sibling files.

CLI:
    .venv/bin/python calibration/report.py --config CONFIG [--out PATH]
                                            [--no-video] [--max-video-mb 25]
"""

import argparse
import base64
import io
import json
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from calibration import optimize, runner, ui_charts, ui_state, ui_theme  # noqa: E402

TEMPLATE = Path(__file__).with_name("report_template.html.j2")
THUMB_WIDTH = 480
MAX_GALLERY = 6

REPORT_CSS = f"""
body {{ background: {ui_theme.PALETTE['bg']}; color: {ui_theme.PALETTE['text']};
       font-family: {ui_theme.FONT_STACK}; margin: 0 auto; padding: 36px 28px;
       max-width: 1100px; }}
h1 {{ font-size: 1.5rem; margin: 0 0 4px 0; }}
h1 .hsub {{ color: {ui_theme.PALETTE['muted']}; font-size: .9rem;
           font-weight: 400; margin-left: 10px; }}
h2 {{ font-size: 1.05rem; margin: 0 0 8px 0; color: {ui_theme.PALETTE['accent2']}; }}
header {{ display: flex; justify-content: space-between; align-items: baseline;
         border-bottom: 1px solid {ui_theme.PALETTE['border']};
         padding-bottom: 14px; margin-bottom: 22px; }}
section {{ margin: 26px 0; }}
.metric-grid {{ display: flex; gap: 12px; flex-wrap: wrap; }}
.metric {{ background: {ui_theme.PALETTE['card']};
          border: 1px solid {ui_theme.PALETTE['border']};
          border-radius: 10px; padding: 12px 18px; min-width: 130px; }}
.metric .k {{ color: {ui_theme.PALETTE['muted']}; font-size: .7rem;
             text-transform: uppercase; letter-spacing: .07em; }}
.metric .v {{ font-size: 1.35rem; font-weight: 600; margin-top: 2px; }}
.gallery {{ display: flex; gap: 12px; flex-wrap: wrap; }}
.gallery figure {{ margin: 0; }}
.gallery img {{ width: 320px; border-radius: 8px;
               border: 1px solid {ui_theme.PALETTE['border']}; }}
figcaption {{ color: {ui_theme.PALETTE['muted']}; font-size: .75rem;
             margin-top: 4px; }}
.video-row {{ display: flex; gap: 16px; flex-wrap: wrap; }}
.video-row figure {{ margin: 0; flex: 1 1 380px; }}
video {{ width: 100%; border-radius: 10px;
        border: 1px solid {ui_theme.PALETTE['border']};
        background: {ui_theme.PALETTE['bg']}; }}
pre, code {{ font-family: {ui_theme.MONO_STACK}; font-size: .82rem; }}
pre {{ background: {ui_theme.PALETTE['bg2']}; padding: 12px 16px;
      border-radius: 8px; border: 1px solid {ui_theme.PALETTE['border']};
      overflow-x: auto; }}
code {{ background: {ui_theme.PALETTE['bg2']}; padding: 1px 6px;
       border-radius: 5px; }}
table.kv {{ border-collapse: collapse; font-size: .85rem; }}
table.kv th, table.kv td {{ text-align: left; padding: 4px 16px 4px 0;
  border-bottom: 1px solid {ui_theme.PALETTE['border']}; }}
table.kv th {{ color: {ui_theme.PALETTE['muted']}; font-weight: 500; }}
.note {{ color: {ui_theme.PALETTE['muted']}; font-size: .8rem; }}
footer {{ margin-top: 36px; border-top: 1px solid {ui_theme.PALETTE['border']};
         padding-top: 12px; }}
"""


def _thumb_data_uri(path: Path, width: int = THUMB_WIDTH) -> str | None:
    """PNG thumbnail as a data URI; None on any trouble (a missing image must
    not kill the report)."""
    try:
        from PIL import Image

        img = Image.open(path).convert("RGB")
        img.thumbnail((width, width * 3 // 4))
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:  # noqa: BLE001
        return None


def _video_entry(label: str, path: Path, *, include_video: bool,
                 max_video_mb: int) -> dict | None:
    if not include_video or not path.exists():
        return None
    size_mb = path.stat().st_size / 1e6
    mime = "video/mp4" if path.suffix == ".mp4" else "image/gif"
    if size_mb <= max_video_mb:
        data = base64.b64encode(path.read_bytes()).decode()
        return {"label": label, "embedded": True,
                "src": f"data:{mime};base64,{data}", "note": None}
    return {"label": label, "embedded": False, "src": path.name,
            "note": f"{size_mb:.0f} MB > {max_video_mb} MB embed budget"}


def _fmt_metric(v) -> str:
    return "—" if v is None else (f"{v:.3f}" if isinstance(v, float) else str(v))


def _load_best(cfg) -> dict | None:
    try:
        return json.loads(cfg.best_json.read_text()) if cfg.best_json.exists() else None
    except (json.JSONDecodeError, OSError):
        return None


def build_report(cfg: "optimize.StudyConfig", out_path: Path | None = None, *,
                 include_video: bool = True, max_video_mb: int = 25) -> Path:
    """Assemble and write the single-file report; returns its path."""
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    from markupsafe import Markup

    out_path = Path(out_path) if out_path is not None else Path(cfg.outdir) / "report.html"
    best_payload = _load_best(cfg)
    best = (best_payload or {}).get("best") or {}
    study = ui_state.load_study(cfg)
    rows = ui_state.trial_rows(study, cfg) if study else []
    spans = ui_state.trial_spans(study) if study else []
    specs = ui_state.response_specs(cfg)

    # ---- summary metrics
    done = [r for r in rows if r["state"] == "complete" and r["loss"] is not None]
    best_loss = min((r["loss"] for r in done), default=None)
    sim_s = sum(s["duration_s"] for s in spans
                if s["duration_s"] is not None and not s["cached"])
    cache_hits = sum(1 for s in spans if s["cached"])
    metrics = [
        {"k": "trials complete", "v": len(done)},
        {"k": "best loss [σ]", "v": _fmt_metric(best_loss)},
        {"k": "noise floor [σ]", "v": f"{cfg.noise_floor():.2f}"},
        {"k": "responses", "v": " + ".join(cfg.enabled_responses()) or "—"},
        {"k": "live sim time", "v": ui_state._human_s(sim_s) if sim_s else "0 s"},
        {"k": "cache hits", "v": cache_hits},
    ]

    # ---- interactive figures (the same builders the cockpit renders)
    figures = []

    def _add_fig(title, fig, note=None):
        # first figure carries the plotly.js CDN tag; the rest reuse it
        html = fig.to_html(full_html=False,
                           include_plotlyjs="cdn" if not figures else False,
                           config={"displaylogo": False})
        figures.append({"title": title, "html": Markup(html), "note": note})

    if rows:
        _add_fig("Convergence vs seed-noise floor",
                 ui_charts.convergence_figure(rows, noise_floor=cfg.noise_floor(),
                                              fail_penalty=cfg.fail_penalty,
                                              specs=specs))
        _add_fig("The friction valley",
                 ui_charts.valley_figure(rows, ui_state.family_anchors(),
                                         cfg.search_bounds),
                 note="trials colored by loss; amber rings = inside every σ band; "
                      "dotted diamonds = the material card's equivalence family")
        for name, spec in specs.items():
            _add_fig(f"{spec['label']} — trials vs target band",
                     ui_charts.response_band_figure(rows, spec))
        _add_fig("Per-response loss breakdown",
                 ui_charts.loss_breakdown_figure(rows, specs,
                                                 fail_penalty=cfg.fail_penalty))
        if spans:
            _add_fig("Trial timeline",
                     ui_charts.timeline_figure(spans),
                     note="cyan = cache hit (free), amber = live simulation, "
                          "red = failed")
    if best_payload:
        items = []
        for name, tgt in (best_payload.get("targets") or {}).items():
            calib = runner.RESPONSES[name]["calib"]
            items.append({"label": calib["label"],
                          "value": best.get(calib["result_key"]),
                          "std": best.get(calib["std_key"]),
                          "target": tgt["target"], "sigma": tgt["sigma"]})
        if items:
            _add_fig("Best set — achieved vs target ± σ",
                     ui_charts.target_bullet_figure(items))

    # ---- material card + gallery + videos
    card_html = (Markup(ui_theme.material_card_html(
        ui_state.material_card_preview(best_payload)))
        if best_payload else None)

    gallery = []
    if study is not None and best.get("trial") is not None:
        detail = ui_state.trial_detail(study, cfg, int(best["trial"]))
        for item in (detail or {}).get("items", [])[:MAX_GALLERY]:
            for img, what in ((item["snapshot"], "snapshot"),
                              (item["fit"], "measurement audit")):
                if img and len(gallery) < MAX_GALLERY:
                    uri = _thumb_data_uri(img)
                    if uri:
                        gallery.append({
                            "caption": f"trial {item['trial']} · {item['response']}"
                                       f" · seed {item['seed']} · {what}",
                            "data_uri": uri})

    videos = []
    for resp, path in ui_state.hero_paths(cfg).items():
        label = {"aor": "heap formation (pour → settle → lift)",
                 "drum": "drum steady-state flow",
                 "drum45": "45° drum steady-state flow"}.get(resp, resp)
        entry = _video_entry(label, path, include_video=include_video,
                             max_video_mb=max_video_mb)
        if entry:
            videos.append(entry)

    # ---- shipped-card validation + evidence
    validation = None
    shipped = REPO_ROOT / "materials" / "wheat.json"
    if shipped.exists():
        try:
            v = json.loads(shipped.read_text()).get("validation")
            if isinstance(v, dict):
                validation = {k: (f"{x:.3f}" if isinstance(x, float) else x)
                              for k, x in v.items()}
        except (json.JSONDecodeError, OSError):
            pass

    config_path = Path(cfg.outdir) / "config.json"
    replay_cmd = (f".venv/bin/python calibration/optimize.py run "
                  f"--config '{optimize._repo_rel(config_path)}'")
    evidence = {
        "study dir": optimize._repo_rel(cfg.outdir),
        "config": optimize._repo_rel(config_path),
        "best trial dir": best.get("trial_dir") or "—",
        "total trials in study": (best_payload or {}).get("n_trials") or len(rows),
    }

    met = (best_payload or {}).get("target_met")
    verdict_pill = Markup(ui_theme.pill(
        "ok" if met else "warn" if met is False else "idle",
        "all responses in band" if met
        else "not inside every band" if met is False else "no result yet"))

    env = Environment(loader=FileSystemLoader(str(TEMPLATE.parent)),
                      autoescape=select_autoescape(["html"]))
    html = env.get_template(TEMPLATE.name).render(
        title=f"{cfg.study_name} — DEM calibration report",
        study_name=cfg.study_name,
        verdict_pill=verdict_pill,
        metrics=metrics,
        card_html=card_html,
        figures=figures,
        gallery=gallery,
        videos=videos,
        validation=validation,
        replay_cmd=replay_cmd,
        evidence=evidence,
        css=Markup(ui_theme.CSS + REPORT_CSS),
        generated=datetime.now().strftime("%Y-%m-%d %H:%M"),
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html)
    return out_path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", required=True, help="study config.json")
    ap.add_argument("--out", default=None, help="output HTML (default: <study>/report.html)")
    ap.add_argument("--no-video", action="store_true", help="skip video embedding")
    ap.add_argument("--max-video-mb", type=int, default=25,
                    help="largest video to inline as base64")
    args = ap.parse_args()
    cfg = optimize.load_config(Path(args.config))
    out = build_report(cfg, Path(args.out) if args.out else None,
                       include_video=not args.no_video,
                       max_video_mb=args.max_video_mb)
    print(out)


if __name__ == "__main__":
    main()
