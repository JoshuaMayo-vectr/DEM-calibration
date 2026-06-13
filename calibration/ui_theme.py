"""Dark mission-control look for the Phase-8.5 calibration cockpit.

Pure presentation constants + tiny HTML snippet builders — no Streamlit, no
state, no calibration logic, so everything here is unit-testable headless and
shared verbatim by the UI (ui.py injects CSS once) and the standalone HTML
report (report.py inlines the same palette). The Streamlit base theme lives in
.streamlit/config.toml and mirrors PALETTE — change both together.
"""

import html

PALETTE = {
    "bg": "#0B1220",        # app background (deep blue-slate)
    "bg2": "#111A2C",       # sidebar / inputs / expanders
    "card": "#152238",      # carded surfaces (metrics, gallery tiles)
    "border": "#22304A",    # card borders + plot grid lines
    "grid": "#22304A",
    "text": "#E2E8F0",
    "muted": "#94A3B8",
    "accent": "#F59E0B",    # amber — primary actions, best-so-far, highlights
    "accent2": "#22D3EE",   # cyan — data traces, secondary series
    "ok": "#34D399",
    "warn": "#FBBF24",
    "err": "#F87171",
}

FONT_STACK = "Inter, -apple-system, 'Segoe UI', sans-serif"
MONO_STACK = "'JetBrains Mono', ui-monospace, Menlo, monospace"

# Status pill kinds -> color. `run` additionally pulses (live run indicator).
_PILL_COLORS = {
    "ok": PALETTE["ok"],
    "run": PALETTE["accent"],
    "idle": PALETTE["muted"],
    "err": PALETTE["err"],
    "pending": PALETTE["accent2"],
    "warn": PALETTE["warn"],
}


def _rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"


def _pill_css() -> str:
    rules = [
        ".pill { display:inline-flex; align-items:center; gap:6px;"
        " padding:2px 10px; border-radius:999px; font-size:0.72rem;"
        " font-weight:600; letter-spacing:.05em; text-transform:uppercase;"
        " border:1px solid transparent; white-space:nowrap; }",
        ".pill::before { content:''; width:7px; height:7px; border-radius:50%;"
        " background: currentColor; }",
        "@keyframes pillpulse { 0%,100% {opacity:1} 50% {opacity:.55} }",
    ]
    for kind, color in _PILL_COLORS.items():
        pulse = " animation: pillpulse 2s ease-in-out infinite;" if kind == "run" else ""
        rules.append(
            f".pill-{kind} {{ color:{color}; background:{_rgba(color, 0.12)};"
            f" border-color:{_rgba(color, 0.35)};{pulse} }}")
    return "\n".join(rules)


CSS = f"""
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

html, body, [data-testid="stAppViewContainer"] {{
  font-family: {FONT_STACK};
}}
code, pre, kbd {{ font-family: {MONO_STACK}; }}

/* ---- metrics become cards -------------------------------------------- */
[data-testid="stMetric"] {{
  background: {PALETTE["card"]};
  border: 1px solid {PALETTE["border"]};
  border-radius: 10px;
  padding: 12px 16px 10px 16px;
}}
[data-testid="stMetricLabel"] {{
  color: {PALETTE["muted"]};
  text-transform: uppercase;
  letter-spacing: .07em;
  font-size: 0.72rem;
}}
[data-testid="stMetricValue"] {{ font-weight: 600; }}

/* ---- bordered containers that hold a pill = our cards ----------------- */
[data-testid="stVerticalBlockBorderWrapper"]:has(.pill) {{
  background: {PALETTE["card"]};
  border-radius: 12px;
}}
/* status tint on gallery cards (graceful no-op where :has unsupported) */
[data-testid="stVerticalBlockBorderWrapper"]:has(.pill-ok)      {{ border: 1px solid {_rgba(PALETTE["ok"], 0.45)}; }}
[data-testid="stVerticalBlockBorderWrapper"]:has(.pill-err)     {{ border: 1px solid {_rgba(PALETTE["err"], 0.45)}; }}
[data-testid="stVerticalBlockBorderWrapper"]:has(.pill-pending) {{ border: 1px solid {_rgba(PALETTE["accent2"], 0.35)}; }}
[data-testid="stVerticalBlockBorderWrapper"]:has(.pill-run)     {{ border: 1px solid {_rgba(PALETTE["accent"], 0.45)}; }}

/* ---- tabs: amber underline, quieter inactive labels ------------------- */
[data-testid="stTabs"] [data-baseweb="tab-highlight"] {{ background: {PALETTE["accent"]}; }}
[data-testid="stTabs"] button[aria-selected="false"] p {{ color: {PALETTE["muted"]}; }}

/* ---- sidebar branding -------------------------------------------------- */
[data-testid="stSidebar"] h1 {{
  letter-spacing: .02em;
  font-weight: 700;
}}

/* ---- expanders + dataframes sit on the secondary surface --------------- */
[data-testid="stExpander"] details {{
  border: 1px solid {PALETTE["border"]};
  border-radius: 10px;
  background: {PALETTE["bg2"]};
}}

{_pill_css()}

/* ---- material card (shared with the HTML report) ----------------------- */
.mc {{ border:1px solid {PALETTE["border"]}; border-radius:12px;
      background:{PALETTE["card"]}; padding:18px 20px; }}
.mc h4 {{ margin:0 0 2px 0; color:{PALETTE["text"]}; }}
.mc .mc-sub {{ color:{PALETTE["muted"]}; font-size:.8rem; margin-bottom:12px; }}
.mc .mc-section {{ color:{PALETTE["muted"]}; font-size:.72rem; font-weight:600;
                  text-transform:uppercase; letter-spacing:.07em;
                  margin:14px 0 6px 0; }}
.mc .mc-params {{ display:flex; flex-wrap:wrap; gap:10px; }}
.mc .mc-param {{ background:{PALETTE["bg2"]}; border:1px solid {PALETTE["border"]};
                border-radius:10px; padding:8px 14px; min-width:110px; }}
.mc .mc-param .v {{ font-size:1.25rem; font-weight:600; font-family:{MONO_STACK}; }}
.mc .mc-param .k {{ color:{PALETTE["accent2"]}; font-size:.78rem; }}
.mc .mc-param .r {{ color:{PALETTE["muted"]}; font-size:.68rem; }}
.mc table {{ width:100%; border-collapse:collapse; font-size:.85rem; }}
.mc td, .mc th {{ padding:5px 10px 5px 0; text-align:left;
                 border-bottom:1px solid {PALETTE["border"]}; }}
.mc th {{ color:{PALETTE["muted"]}; font-weight:500; }}
.mc .mono {{ font-family:{MONO_STACK}; }}
.mc .mc-foot {{ color:{PALETTE["muted"]}; font-size:.72rem; margin-top:12px; }}
"""


def pill(kind: str, label: str) -> str:
    """An inline status pill. kind in {ok, run, idle, err, pending, warn}."""
    if kind not in _PILL_COLORS:
        kind = "idle"
    return f'<span class="pill pill-{kind}">{html.escape(str(label))}</span>'


def _fmt(v, nd: int = 4) -> str:
    """Compact numeric formatting for card values; non-numbers pass through."""
    if isinstance(v, bool) or v is None:
        return {True: "yes", False: "no", None: "—"}[v]
    if isinstance(v, (int, float)):
        return f"{v:.{nd}g}"
    return str(v)


def _kv_lines(d: dict) -> str:
    rows = []
    for k, v in d.items():
        if isinstance(v, dict):
            v = ", ".join(f"{ik} {_fmt(iv)}" for ik, iv in v.items()
                          if not isinstance(iv, (dict, list)))
        elif isinstance(v, list):
            v = ", ".join(_fmt(x) for x in v)
        rows.append(f"<tr><th>{html.escape(str(k))}</th>"
                    f"<td class='mono'>{html.escape(_fmt(v))}</td></tr>")
    return f"<table>{''.join(rows)}</table>"


def material_card_html(card: dict) -> str:
    """The material-card preview as styled HTML (Results tab + report).

    Takes the dict ui_state.material_card_preview returns; every section is
    optional and rendered defensively — a sparse best.json must still produce
    a readable card, never an exception.
    """
    name = (card.get("evidence") or {}).get("study_name") or "calibration study"
    met = card.get("target_met")
    verdict = (pill("ok", "all responses in band") if met
               else pill("warn", "not inside every band") if met is False
               else pill("idle", "no verdict yet"))

    parts = [f"<div class='mc'><h4>Material card preview &nbsp;{verdict}</h4>",
             f"<div class='mc-sub'>{html.escape(str(card.get('_preview', '')))}"
             f" · study <b>{html.escape(str(name))}</b></div>"]

    params = card.get("parameters") or {}
    if params:
        parts.append("<div class='mc-section'>Calibrated parameters</div>"
                     "<div class='mc-params'>")
        for k, spec in params.items():
            parts.append(
                "<div class='mc-param'>"
                f"<div class='k'>{html.escape(str(k))}</div>"
                f"<div class='v'>{html.escape(_fmt((spec or {}).get('value')))}</div>"
                f"<div class='r'>{html.escape(str((spec or {}).get('role', '')))}</div>"
                "</div>")
        parts.append("</div>")

    responses = card.get("responses") or {}
    if responses:
        parts.append("<div class='mc-section'>Responses</div><table>"
                     "<tr><th>response</th><th>achieved</th><th>target</th>"
                     "<th>band</th></tr>")
        for rname, r in responses.items():
            r = r or {}
            v, std = r.get("value"), r.get("std")
            tgt, sig = r.get("target"), r.get("target_sigma")
            achieved = _fmt(v) + (f" ± {_fmt(std)}" if std is not None else "")
            target = (f"{_fmt(tgt)} ± {_fmt(sig)}" if tgt is not None else
                      "uncalibrated" if r.get("calibrated") is False else "—")
            if v is not None and tgt is not None and sig:
                band = (pill("ok", "in band") if abs(v - tgt) <= sig
                        else pill("err", f"{abs(v - tgt) / sig:.1f}σ off"))
            else:
                band = pill("idle", "free check")
            parts.append(f"<tr><th>{html.escape(str(rname))}</th>"
                         f"<td class='mono'>{html.escape(achieved)}</td>"
                         f"<td class='mono'>{html.escape(target)}</td>"
                         f"<td>{band}</td></tr>")
        parts.append("</table>")

    for section, key in (("Engine", "engine"), ("Contact model", "contact_model"),
                         ("Fixed inputs", "fixed_inputs")):
        block = card.get(key)
        if isinstance(block, dict) and block:
            parts.append(f"<div class='mc-section'>{section}</div>")
            parts.append(_kv_lines(block))

    ev = card.get("evidence") or {}
    foot = " · ".join(f"{k}: {_fmt(v)}" for k, v in ev.items() if v is not None)
    if foot:
        parts.append(f"<div class='mc-foot'>{html.escape(foot)}</div>")
    parts.append("</div>")
    return "".join(parts)
