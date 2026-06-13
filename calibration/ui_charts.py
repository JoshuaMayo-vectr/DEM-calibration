"""Plotly figure builders for the calibration cockpit (Phase 8.5 premium).

Pure presentation: plain lists/dicts in (ui_state extracts them from the
study/config/files), go.Figure out. No Streamlit, no optuna, no OVITO — every
builder is unit-testable headless from literal fixtures, and the HTML report
(report.py) reuses these figures verbatim so the UI and the report can never
drift apart. All figures share the dark mission-control styling via _dark().

The matplotlib figures in optimize.py (history/contour/valley_compare) remain
the CLI/report-grade static artifacts; these are their live, interactive
counterparts built from the same study data.
"""

from datetime import datetime

import plotly.graph_objects as go
from plotly.subplots import make_subplots

try:
    from calibration import ui_theme
except ImportError:                       # script-style execution
    import ui_theme

PALETTE = ui_theme.PALETTE
COLORWAY = [PALETTE["accent2"], PALETTE["accent"], PALETTE["ok"],
            PALETTE["err"], "#A78BFA", "#F472B6"]


def _dark(fig: go.Figure, *, height: int = 380, title: str | None = None) -> go.Figure:
    """Shared dark layout: transparent backgrounds (the app/report bg shows
    through), palette-matched grid + fonts. Every builder funnels through here
    so the cockpit stays visually coherent."""
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=ui_theme.FONT_STACK, size=12, color=PALETTE["text"]),
        margin=dict(l=46, r=20, t=46 if title else 18, b=40),
        height=height,
        colorway=COLORWAY,
        hoverlabel=dict(font_family=ui_theme.FONT_STACK,
                        bgcolor=PALETTE["bg2"], bordercolor=PALETTE["border"]),
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(size=11)),
    )
    if title:
        fig.update_layout(title=dict(text=title, font=dict(size=13),
                                     x=0.0, xanchor="left"))
    fig.update_xaxes(gridcolor=PALETTE["grid"], zeroline=False,
                     linecolor=PALETTE["border"])
    fig.update_yaxes(gridcolor=PALETTE["grid"], zeroline=False,
                     linecolor=PALETTE["border"])
    return fig


def _completed(rows: list[dict]) -> list[dict]:
    done = [r for r in rows if r.get("state") == "complete" and r.get("loss") is not None]
    done.sort(key=lambda r: r["trial"])
    return done


def _param_line(r: dict) -> str:
    parts = [f"{d} {r[d]:.3f}" for d in ("fric", "rollfric", "rest")
             if isinstance(r.get(d), (int, float))]
    return " · ".join(parts)


def _response_lines(r: dict, specs: dict | None) -> str:
    if not specs:
        return ""
    lines = []
    for spec in specs.values():
        v = r.get(spec["result_key"])
        if v is None:
            continue
        std = r.get(spec["std_key"])
        lines.append(f"{spec['result_key']} {v:.2f}"
                     + (f" ± {std:.2f}" if isinstance(std, (int, float)) else ""))
    return ("<br>" + "<br>".join(lines)) if lines else ""


def _p90(values: list[float]) -> float:
    vals = sorted(values)
    return vals[int(0.9 * (len(vals) - 1))] if vals else 1.0


# ------------------------------------------------------------- convergence

def convergence_figure(rows: list[dict], *, noise_floor: float,
                       fail_penalty: float = 100.0,
                       specs: dict | None = None,
                       height: int = 380) -> go.Figure:
    """Loss per trial + best-so-far step line + shaded seed-noise floor.

    Failed trials (loss >= fail_penalty) draw as red ✕ pinned just under the
    y-cap so the finite penalty never flattens the real losses. customdata
    carries trial numbers for click-to-inspect.
    """
    done = _completed(rows)
    ok = [r for r in done if r["loss"] < fail_penalty]
    failed = [r for r in done if r["loss"] >= fail_penalty]

    ymax = max([r["loss"] for r in ok], default=0.0)
    ycap = 1.15 * max(noise_floor * 3.0, ymax, 0.5)

    fig = go.Figure()
    if noise_floor > 0:
        fig.add_hrect(y0=0.0, y1=noise_floor, line_width=0,
                      fillcolor=PALETTE["ok"], opacity=0.08)
        fig.add_hline(y=noise_floor, line_dash="dot", line_width=1.2,
                      line_color=PALETTE["ok"],
                      annotation_text=f"seed-noise floor ≈ {noise_floor:.2f}σ",
                      annotation_font=dict(size=10, color=PALETTE["ok"]),
                      annotation_position="top right")
    if ok:
        best_x, best_y, run_min = [], [], None
        for r in ok:
            if run_min is None or r["loss"] < run_min:
                run_min = r["loss"]
            best_x.append(r["trial"])
            best_y.append(run_min)
        fig.add_trace(go.Scatter(
            x=best_x, y=best_y, mode="lines", name="best so far",
            line=dict(color=PALETTE["accent"], width=2, shape="hv"),
            hoverinfo="skip"))
        fig.add_trace(go.Scatter(
            x=[r["trial"] for r in ok], y=[r["loss"] for r in ok],
            mode="markers", name="trial loss",
            customdata=[r["trial"] for r in ok],
            marker=dict(color=PALETTE["accent2"], size=8, opacity=0.9,
                        line=dict(width=1, color=PALETTE["bg"])),
            text=[f"trial {r['trial']}<br>loss {r['loss']:.3f}σ<br>"
                  f"{_param_line(r)}{_response_lines(r, specs)}" for r in ok],
            hoverinfo="text"))
    if failed:
        fig.add_trace(go.Scatter(
            x=[r["trial"] for r in failed], y=[ycap * 0.97] * len(failed),
            mode="markers", name="failed (penalty)",
            customdata=[r["trial"] for r in failed],
            marker=dict(symbol="x", color=PALETTE["err"], size=9),
            text=[f"trial {r['trial']}<br>FAILED — penalty {r['loss']:.0f}<br>"
                  f"{_param_line(r)}" for r in failed],
            hoverinfo="text"))
    fig.update_yaxes(range=[0, ycap], title_text="loss [σ]")
    fig.update_xaxes(title_text="trial")
    return _dark(fig, height=height, title="Convergence vs seed-noise floor")


# ------------------------------------------------------------- valley map

def valley_figure(rows: list[dict], anchors: list[dict], bounds: dict, *,
                  in_band_loss: float = 1.0, height: int = 380) -> go.Figure:
    """The project's story chart: trials in (fric, rollfric) colored by loss,
    in-band trials ringed in amber, the material card's equivalence-family
    anchors overlaid as the dotted valley ridge. Axes are pinned to the search
    bounds so the box, not the data, frames the view."""
    done = [r for r in _completed(rows)
            if isinstance(r.get("fric"), (int, float))
            and isinstance(r.get("rollfric"), (int, float))]

    fig = go.Figure()
    if done:
        losses = [r["loss"] for r in done]
        cmax = max(_p90(losses), in_band_loss * 1.5)
        fig.add_trace(go.Scatter(
            x=[r["fric"] for r in done], y=[r["rollfric"] for r in done],
            mode="markers", name="trials",
            customdata=[r["trial"] for r in done],
            marker=dict(color=losses, colorscale="Plasma_r", cmin=0.0, cmax=cmax,
                        size=10, opacity=0.95,
                        line=dict(width=1, color=PALETTE["bg"]),
                        colorbar=dict(title=dict(text="loss [σ]", font=dict(size=11)),
                                      thickness=12, outlinewidth=0)),
            text=[f"trial {r['trial']}<br>loss {r['loss']:.3f}σ<br>{_param_line(r)}"
                  for r in done],
            hoverinfo="text"))
        in_band = [r for r in done if r["loss"] <= in_band_loss]
        if in_band:
            fig.add_trace(go.Scatter(
                x=[r["fric"] for r in in_band], y=[r["rollfric"] for r in in_band],
                mode="markers", name=f"in band (≤ {in_band_loss:g}σ)",
                customdata=[r["trial"] for r in in_band],
                marker=dict(symbol="circle-open", size=16,
                            line=dict(width=2.5, color=PALETTE["accent"]),
                            color="rgba(0,0,0,0)"),
                hoverinfo="skip"))
    if anchors:
        anc = sorted(anchors, key=lambda a: a["fric"])
        fig.add_trace(go.Scatter(
            x=[a["fric"] for a in anc], y=[a["rollfric"] for a in anc],
            mode="lines+markers", name="equivalence family",
            line=dict(dash="dot", color=PALETTE["accent2"], width=1.5),
            marker=dict(symbol="diamond", size=8, color=PALETTE["accent2"]),
            text=[("anchor"
                   + (f"<br>AoR {a['aor_deg']:.1f}°" if a.get("aor_deg") is not None else "")
                   + (f"<br>drum {a['drum_aor_deg']:.1f}°"
                      if a.get("drum_aor_deg") is not None else ""))
                  for a in anc],
            hoverinfo="text"))
    if "fric" in bounds:
        fig.update_xaxes(range=list(bounds["fric"]))
    if "rollfric" in bounds:
        fig.update_yaxes(range=list(bounds["rollfric"]))
    fig.update_xaxes(title_text="fric (sliding)")
    fig.update_yaxes(title_text="rollfric (rolling)")
    return _dark(fig, height=height, title="Friction valley — search box")


# ------------------------------------------------------------- response bands

def response_band_figure(rows: list[dict], spec: dict, *,
                         height: int = 300) -> go.Figure:
    """One response across trials: value ± seed-std markers (green in band,
    red out) against the shaded target ± σ band."""
    done = [r for r in _completed(rows) if r.get(spec["result_key"]) is not None]
    target, sigma = spec["target"], spec["sigma"]

    fig = go.Figure()
    fig.add_hrect(y0=target - sigma, y1=target + sigma, line_width=0,
                  fillcolor=PALETTE["ok"], opacity=0.10)
    fig.add_hline(y=target, line_dash="dash", line_width=1.2,
                  line_color=PALETTE["ok"],
                  annotation_text=f"target {target:g} ± {sigma:g}",
                  annotation_font=dict(size=10, color=PALETTE["ok"]),
                  annotation_position="top right")
    if done:
        vals = [r[spec["result_key"]] for r in done]
        stds = [r.get(spec["std_key"]) or 0.0 for r in done]
        colors = [PALETTE["ok"] if abs(v - target) <= sigma else PALETTE["err"]
                  for v in vals]
        fig.add_trace(go.Scatter(
            x=[r["trial"] for r in done], y=vals, mode="markers",
            name=spec["result_key"],
            customdata=[r["trial"] for r in done],
            error_y=dict(type="data", array=stds, color=PALETTE["muted"],
                         thickness=1.2, width=3),
            marker=dict(color=colors, size=9,
                        line=dict(width=1, color=PALETTE["bg"])),
            text=[f"trial {r['trial']}<br>{spec['result_key']} "
                  f"{v:.2f} ± {s:.2f}" for r, v, s in zip(done, vals, stds)],
            hoverinfo="text"))
    fig.update_xaxes(title_text="trial")
    fig.update_yaxes(title_text=spec["result_key"])
    return _dark(fig, height=height, title=spec.get("label", spec["result_key"]))


# ------------------------------------------------------------- loss breakdown

def loss_breakdown_figure(rows: list[dict], specs: dict, *,
                          fail_penalty: float = 100.0,
                          height: int = 300) -> go.Figure:
    """Stacked per-response loss terms, recomputed exactly as the optimizer's
    objective composes them (weight · |value − target| / σ; a missing value
    means that term hit the fail penalty — drawn capped, flagged in hover)."""
    done = _completed(rows)
    trials = [r["trial"] for r in done]

    real_terms: dict[str, list[float]] = {}
    hover: dict[str, list[str]] = {}
    for name, spec in specs.items():
        terms, texts = [], []
        for r in done:
            v = r.get(spec["result_key"])
            if v is None:
                terms.append(None)
                texts.append(f"trial {r['trial']}<br>{name}: FAILED (penalty "
                             f"{spec['weight'] * fail_penalty:g})")
            else:
                t = spec["weight"] * abs(v - spec["target"]) / spec["sigma"]
                terms.append(t)
                texts.append(f"trial {r['trial']}<br>{name}: {t:.3f}σ")
        real_terms[name] = terms
        hover[name] = texts

    finite = [t for terms in real_terms.values() for t in terms if t is not None]
    cap = 1.15 * max(finite, default=1.0) * max(len(specs), 1)

    fig = go.Figure()
    for i, (name, terms) in enumerate(real_terms.items()):
        fig.add_trace(go.Bar(
            x=trials,
            y=[min(t, cap) if t is not None else cap for t in terms],
            name=name, text=None, customdata=trials,
            marker=dict(color=COLORWAY[i % len(COLORWAY)],
                        line=dict(width=0)),
            hovertext=hover[name], hoverinfo="text"))
    fig.update_layout(barmode="stack", bargap=0.35)
    fig.update_xaxes(title_text="trial")
    fig.update_yaxes(title_text="loss term [σ]", range=[0, cap * 1.05])
    return _dark(fig, height=height, title="Per-response loss breakdown")


# ------------------------------------------------------------- target bullets

def target_bullet_figure(items: list[dict], *, height: int | None = None) -> go.Figure:
    """Results-tab bullet chart: one row per response — target ± σ band,
    dashed target line, achieved value with seed-std error bar (green/red by
    in-band). Rows have independent x-axes (responses live on different
    scales). items: [{label, value, std, target, sigma}]."""
    items = [i for i in items if i.get("target") is not None]
    n = max(len(items), 1)
    height = height if height is not None else 96 * n + 60
    fig = make_subplots(rows=n, cols=1, shared_xaxes=False,
                        vertical_spacing=min(0.18, 0.5 / n))

    for i, item in enumerate(items, start=1):
        target, sigma = item["target"], item["sigma"]
        value, std = item.get("value"), item.get("std") or 0.0
        lo = target - 3.2 * sigma
        hi = target + 3.2 * sigma
        if value is not None:
            lo = min(lo, value - 1.5 * std - 0.2 * sigma)
            hi = max(hi, value + 1.5 * std + 0.2 * sigma)
        fig.add_shape(type="rect", x0=target - sigma, x1=target + sigma,
                      y0=-0.5, y1=0.5, line_width=0,
                      fillcolor=PALETTE["ok"], opacity=0.18, row=i, col=1)
        fig.add_shape(type="line", x0=target, x1=target, y0=-0.55, y1=0.55,
                      line=dict(dash="dash", color=PALETTE["ok"], width=1.4),
                      row=i, col=1)
        if value is not None:
            in_band = abs(value - target) <= sigma
            color = PALETTE["ok"] if in_band else PALETTE["err"]
            fig.add_trace(go.Scatter(
                x=[value], y=[0], mode="markers",
                error_x=dict(type="data", array=[std], color=PALETTE["muted"],
                             thickness=1.4, width=5),
                marker=dict(symbol="diamond", size=15, color=color,
                            line=dict(width=1.5, color=PALETTE["bg"])),
                text=[f"{item.get('label', '')}<br>achieved {value:.2f} ± {std:.2f}"
                      f"<br>target {target:g} ± {sigma:g}"],
                hoverinfo="text", showlegend=False), row=i, col=1)
        fig.update_xaxes(range=[lo, hi], row=i, col=1)
        fig.update_yaxes(visible=False, range=[-1, 1], row=i, col=1)
        fig.add_annotation(text=item.get("label", ""), xref="x domain",
                           yref="y domain", x=0.0, y=1.25, showarrow=False,
                           font=dict(size=12, color=PALETTE["muted"]),
                           row=i, col=1)
    return _dark(fig, height=height, title="Achieved vs target ± σ")


# ------------------------------------------------------------- PSD preview

def psd_figure(psd_mm: list, *, name: str = "", height: int = 220) -> go.Figure:
    """Particle-size distribution preview: mass fraction per diameter bin.
    psd_mm: [[diameter_mm, mass_frac], ...]."""
    bins = sorted(((float(d), float(w)) for d, w in psd_mm), key=lambda b: b[0])
    fig = go.Figure(go.Bar(
        x=[d for d, _ in bins], y=[w for _, w in bins],
        width=[min(0.25, max(0.05, (bins[-1][0] - bins[0][0]) / (4 * len(bins)) or 0.1))] * len(bins)
        if len(bins) > 1 else None,
        marker=dict(color=PALETTE["accent2"], line=dict(width=0)),
        text=[f"{w:.0%}" for _, w in bins], textposition="outside",
        textfont=dict(size=10, color=PALETTE["muted"]),
        hovertext=[f"{d:g} mm · {w:.1%} by mass" for d, w in bins],
        hoverinfo="text", showlegend=False))
    fig.update_xaxes(title_text="particle diameter [mm]")
    fig.update_yaxes(title_text="mass fraction", range=[0, max(w for _, w in bins) * 1.25])
    title = f"PSD — {name}" if name else "Particle-size distribution"
    return _dark(fig, height=height, title=title)


# ------------------------------------------------------------- 3D dump viewer

def dump_scatter3d_figure(df, *, color_by: str = "z",
                          height: int = 620) -> go.Figure:
    """Interactive 3-D of an actual final dump (~4–6 k particles is comfortable
    WebGL territory). Marker size is SCREEN pixels, not data units — radius is
    mapped linearly onto 2.5–5 px and the true radius lives in the hover; the
    equal-aspect scene keeps the geometry honest even if sizes can't be."""
    r = df["radius"]
    rmin, rmax = float(r.min()), float(r.max())
    if rmax > rmin:
        sizes = 2.5 + (r - rmin) / (rmax - rmin) * 2.5
    else:
        sizes = [3.5] * len(df)

    color_vals = df[color_by] if color_by in df else df["z"]
    fig = go.Figure(go.Scatter3d(
        x=df["x"], y=df["y"], z=df["z"], mode="markers",
        marker=dict(size=list(sizes), color=list(color_vals),
                    colorscale="Viridis", opacity=0.85,
                    colorbar=dict(title=dict(text=color_by, font=dict(size=11)),
                                  thickness=12, outlinewidth=0),
                    line=dict(width=0)),
        text=[f"r {rad * 1000:.2f} mm<br>z {z * 1000:.1f} mm"
              for rad, z in zip(df["radius"], df["z"])],
        hoverinfo="text"))
    axis = dict(gridcolor=PALETTE["grid"], backgroundcolor="rgba(0,0,0,0)",
                zerolinecolor=PALETTE["grid"], showspikes=False)
    fig.update_layout(scene=dict(aspectmode="data",
                                 xaxis={**axis, "title": "x [m]"},
                                 yaxis={**axis, "title": "y [m]"},
                                 zaxis={**axis, "title": "z [m]"}),
                      scene_camera=dict(eye=dict(x=1.6, y=0.9, z=0.7)))
    return _dark(fig, height=height)


# ------------------------------------------------------------- trial timeline

_SPAN_COLORS = {
    "cached": PALETTE["accent2"],
    "live": PALETTE["accent"],
    "failed": PALETTE["err"],
    "running": PALETTE["muted"],
}


def _span_kind(span: dict) -> str:
    state = span.get("state", "")
    if state == "running" or span.get("end") is None:
        return "running"
    if state in ("fail", "pruned"):
        return "failed"
    return "cached" if span.get("cached") else "live"


def timeline_figure(spans: list[dict], *, now: datetime | None = None,
                    height: int | None = None) -> go.Figure:
    """Horizontal time bars, newest trial on top: cyan = cache hit (instant),
    amber = live sim, red = failed, grey = still running (bar drawn to `now`).
    Makes the machine's work — and the cache's free lunches — visible."""
    now = now or datetime.now()
    spans = sorted(spans, key=lambda s: s["trial"], reverse=True)
    height = height if height is not None else max(220, 26 * len(spans) + 90)

    labels, bases, widths, colors, texts = [], [], [], [], []
    for s in spans:
        start = s.get("start")
        if start is None:
            continue
        end = s.get("end") or now
        dur = max((end - start).total_seconds(), 0.05)   # visible sliver for cache hits
        kind = _span_kind(s)
        labels.append(f"trial {s['trial']}")
        bases.append(start)
        widths.append(dur * 1000.0)                       # ms on a date axis
        colors.append(_SPAN_COLORS[kind])
        if kind == "running":
            texts.append(f"trial {s['trial']} · running, {dur:.0f} s so far")
        elif kind == "cached":
            texts.append(f"trial {s['trial']} · cache hit, {s['duration_s']:.2f} s")
        elif kind == "failed":
            texts.append(f"trial {s['trial']} · failed after {s['duration_s']:.0f} s")
        else:
            texts.append(f"trial {s['trial']} · {s['duration_s']:.0f} s")

    fig = go.Figure(go.Bar(
        y=labels, x=widths, base=bases, orientation="h",
        marker=dict(color=colors, line=dict(width=0)),
        hovertext=texts, hoverinfo="text", showlegend=False))
    fig.update_xaxes(type="date", title_text="wall clock")
    fig.update_yaxes(autorange="reversed", tickfont=dict(size=10))
    return _dark(fig, height=height, title="Trial timeline — cyan = cache hit, amber = live sim")
