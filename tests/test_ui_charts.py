"""Tests for calibration/ui_charts.py — pure plotly builders from literal
fixtures. No optuna, no streamlit, no files: rows/specs/spans are plain dicts,
exactly what ui_state hands the builders at runtime."""

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from calibration import ui_charts  # noqa: E402

SPECS = {
    "aor": {"label": "Heap AoR", "result_key": "aor", "std_key": "aor_std",
            "fit_png": "profile_fit.png", "target": 27.0, "sigma": 1.5,
            "weight": 1.0},
    "drum": {"label": "Drum AoR", "result_key": "drum_aor",
             "std_key": "drum_aor_std", "fit_png": "drum_fit.png",
             "target": 36.17, "sigma": 3.1, "weight": 1.0},
}

ROWS = [
    {"trial": 2, "state": "complete", "loss": 0.5, "fric": 0.40,
     "rollfric": 0.14, "rest": 0.58, "aor": 26.6, "aor_std": 0.4,
     "drum_aor": 37.0, "drum_aor_std": 0.3},
    {"trial": 1, "state": "complete", "loss": 200.0, "fric": 0.30,
     "rollfric": 0.20, "rest": 0.40, "aor": None, "aor_std": None,
     "drum_aor": None, "drum_aor_std": None},                  # failed (penalty)
    {"trial": 0, "state": "complete", "loss": 1.8, "fric": 0.60,
     "rollfric": 0.08, "rest": 0.50, "aor": 24.5, "aor_std": 0.9,
     "drum_aor": 33.0, "drum_aor_std": 0.5},
    {"trial": 3, "state": "running", "loss": None, "fric": 0.5,
     "rollfric": 0.1, "rest": 0.5},
]

ANCHORS = [{"fric": 0.25, "rollfric": 0.22, "aor_deg": 27.1, "drum_aor_deg": 38.2},
           {"fric": 0.60, "rollfric": 0.12, "aor_deg": 26.9, "drum_aor_deg": 38.0}]
BOUNDS = {"fric": (0.20, 0.80), "rollfric": (0.05, 0.25), "rest": (0.30, 0.70)}


def _trace_names(fig):
    return [t.name for t in fig.data]


# ------------------------------------------------------------- convergence
def test_convergence_traces_and_floor():
    fig = ui_charts.convergence_figure(ROWS, noise_floor=0.25,
                                       fail_penalty=100.0, specs=SPECS)
    assert isinstance(fig, go.Figure)
    names = _trace_names(fig)
    assert "best so far" in names and "trial loss" in names
    assert "failed (penalty)" in names
    best = next(t for t in fig.data if t.name == "best so far")
    assert best.line.shape == "hv"
    # noise floor: one shaded rect + one line shape
    kinds = [s.type for s in fig.layout.shapes]
    assert "rect" in kinds and "line" in kinds
    # the y-cap excludes the 200-loss penalty from flattening the plot
    assert fig.layout.yaxis.range[1] < 100
    ok = next(t for t in fig.data if t.name == "trial loss")
    assert list(ok.customdata) == [0, 2]            # ascending trials, real losses


def test_convergence_empty_rows():
    fig = ui_charts.convergence_figure([], noise_floor=0.0)
    assert isinstance(fig, go.Figure)
    assert len(fig.data) == 0


# ------------------------------------------------------------- valley
def test_valley_overlays_anchors_and_in_band():
    fig = ui_charts.valley_figure(ROWS, ANCHORS, BOUNDS, in_band_loss=1.0)
    names = _trace_names(fig)
    assert "trials" in names and "equivalence family" in names
    assert any(n and n.startswith("in band") for n in names)
    assert list(fig.layout.xaxis.range) == [0.20, 0.80]
    assert list(fig.layout.yaxis.range) == [0.05, 0.25]
    fam = next(t for t in fig.data if t.name == "equivalence family")
    assert list(fam.x) == sorted(fam.x)             # sorted by fric -> a ridge line


def test_valley_no_anchors_no_trace():
    fig = ui_charts.valley_figure(ROWS, [], BOUNDS)
    assert "equivalence family" not in _trace_names(fig)


def test_valley_empty_rows_safe():
    fig = ui_charts.valley_figure([], [], {})
    assert isinstance(fig, go.Figure)


# ------------------------------------------------------------- response band
def test_response_band_colors_split():
    fig = ui_charts.response_band_figure(ROWS, SPECS["aor"])
    pts = next(t for t in fig.data if t.mode == "markers")
    colors = list(pts.marker.color)
    # 26.6 in band (ok), 24.5 out of band (err)
    assert colors[0] != colors[1]
    assert len(fig.layout.shapes) >= 2              # band rect + target line


def test_response_band_empty():
    fig = ui_charts.response_band_figure([], SPECS["aor"])
    assert isinstance(fig, go.Figure)


# ------------------------------------------------------------- loss breakdown
def test_loss_breakdown_stacks_and_caps():
    fig = ui_charts.loss_breakdown_figure(ROWS, SPECS, fail_penalty=100.0)
    assert fig.layout.barmode == "stack"
    assert len(fig.data) == 2                       # one Bar per response
    assert all(isinstance(t, go.Bar) for t in fig.data)
    ymax = fig.layout.yaxis.range[1]
    assert ymax < 100                               # penalty capped for display
    for t in fig.data:
        assert max(t.y) <= ymax


# ------------------------------------------------------------- target bullets
def test_target_bullet_rows_and_colors():
    items = [{"label": "Heap AoR", "value": 26.6, "std": 0.4,
              "target": 27.0, "sigma": 1.5},
             {"label": "Drum AoR", "value": 41.0, "std": 0.2,
              "target": 36.17, "sigma": 3.1}]
    fig = ui_charts.target_bullet_figure(items)
    markers = [t for t in fig.data if t.mode == "markers"]
    assert len(markers) == 2
    assert markers[0].marker.color != markers[1].marker.color   # in vs out of band
    assert len(fig.layout.shapes) == 4              # (band rect + target line) x 2


def test_target_bullet_handles_missing_value():
    fig = ui_charts.target_bullet_figure(
        [{"label": "x", "value": None, "std": None, "target": 27.0, "sigma": 1.5}])
    assert isinstance(fig, go.Figure)


# ------------------------------------------------------------- PSD preview
def test_psd_figure():
    fig = ui_charts.psd_figure([[3.4, 0.25], [3.7, 0.5], [4.0, 0.25]], name="wheat")
    assert isinstance(fig, go.Figure)
    bar = fig.data[0]
    assert list(bar.x) == [3.4, 3.7, 4.0]
    assert sum(bar.y) == pytest.approx(1.0)
    fig1 = ui_charts.psd_figure([[5.0, 1.0]])               # single bin survives
    assert isinstance(fig1, go.Figure)


# ------------------------------------------------------------- 3D dump scatter
def test_dump_scatter3d_aspect_and_sizes():
    df = pd.DataFrame({
        "x": [0.0, 0.01, 0.02], "y": [0.0, 0.01, 0.0],
        "z": [0.0, 0.005, 0.01], "radius": [0.0017, 0.0019, 0.0020]})
    fig = ui_charts.dump_scatter3d_figure(df, color_by="radius")
    assert fig.layout.scene.aspectmode == "data"
    trace = fig.data[0]
    sizes = list(trace.marker.size)
    assert min(sizes) >= 2.5 and max(sizes) <= 5.0
    assert sizes[0] < sizes[-1]                     # bigger radius -> bigger marker


def test_dump_scatter3d_constant_radius():
    df = pd.DataFrame({"x": [0, 1], "y": [0, 1], "z": [0, 1],
                       "radius": [0.002, 0.002]})
    fig = ui_charts.dump_scatter3d_figure(df)
    assert all(s == 3.5 for s in fig.data[0].marker.size)


# ------------------------------------------------------------- timeline
def test_timeline_colors_and_running_span():
    t0 = datetime(2026, 6, 13, 9, 0, 0)
    spans = [
        {"trial": 0, "state": "complete", "start": t0,
         "end": t0 + timedelta(seconds=1), "duration_s": 1.0, "cached": True},
        {"trial": 1, "state": "complete", "start": t0 + timedelta(minutes=1),
         "end": t0 + timedelta(minutes=5), "duration_s": 240.0, "cached": False},
        {"trial": 2, "state": "fail", "start": t0 + timedelta(minutes=5),
         "end": t0 + timedelta(minutes=6), "duration_s": 60.0, "cached": False},
        {"trial": 3, "state": "running", "start": t0 + timedelta(minutes=6),
         "end": None, "duration_s": None, "cached": False},
    ]
    fig = ui_charts.timeline_figure(spans, now=t0 + timedelta(minutes=8))
    bar = fig.data[0]
    colors = list(bar.marker.color)
    assert colors[0] == ui_charts._SPAN_COLORS["running"]   # newest first
    assert colors[1] == ui_charts._SPAN_COLORS["failed"]
    assert colors[2] == ui_charts._SPAN_COLORS["live"]
    assert colors[3] == ui_charts._SPAN_COLORS["cached"]
    # running bar drawn to `now`: 2 minutes
    assert bar.x[0] == pytest.approx(120_000.0)
    assert fig.layout.yaxis.autorange == "reversed"


def test_timeline_empty():
    fig = ui_charts.timeline_figure([])
    assert isinstance(fig, go.Figure)
