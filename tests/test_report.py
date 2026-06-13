"""Tests for calibration/report.py — the single-file HTML report builds from
a stub study, embeds the plotly CDN tag exactly once, carries the replay
command, stays small without video, and degrades gracefully with no
best.json. Reuses the test_ui_state stub-study fixtures."""

import sys
from pathlib import Path

import optuna
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from calibration import optimize, report  # noqa: E402
from tests.test_ui_state import _make_cfg, _stub_study  # noqa: E402

optuna.logging.set_verbosity(optuna.logging.WARNING)


@pytest.fixture
def study_cfg(tmp_path, monkeypatch):
    cfg = _make_cfg(tmp_path)
    Path(cfg.outdir).mkdir(parents=True, exist_ok=True)
    optimize.save_config(cfg, Path(cfg.outdir) / "config.json")
    return cfg


def test_report_builds_from_stub_study(study_cfg, monkeypatch):
    study = _stub_study(study_cfg, monkeypatch, n_trials=3)
    optimize.write_best(study, cfg=study_cfg)
    out = report.build_report(study_cfg)

    assert out.exists()
    html = out.read_text()
    assert study_cfg.study_name in html
    assert html.count("cdn.plot.ly") == 1                 # plotly.js exactly once
    assert html.count("plotly-graph-div") >= 3            # interactive figures
    assert "optimize.py run --config" in html             # replay command
    assert "Material card preview" in html
    assert out.stat().st_size < 2_000_000                 # < 2 MB without video


def test_report_without_best_json(study_cfg, monkeypatch):
    _stub_study(study_cfg, monkeypatch, n_trials=2)       # study but no best.json
    out = report.build_report(study_cfg)
    html = out.read_text()
    assert "No best.json yet" in html
    assert "no result yet" in html                        # idle verdict pill


def test_report_without_study(study_cfg):
    out = report.build_report(study_cfg)                  # config only
    assert out.exists()
    assert "No best.json yet" in out.read_text()


def test_report_video_budget(study_cfg, monkeypatch):
    study = _stub_study(study_cfg, monkeypatch, n_trials=2)
    optimize.write_best(study, cfg=study_cfg)
    big = Path(study_cfg.outdir) / "hero_aor.mp4"
    big.write_bytes(b"0" * 2_000_000)                     # 2 MB fake video

    html = report.build_report(study_cfg, max_video_mb=1).read_text()
    assert "embed budget" in html                         # referenced, not inlined
    assert "base64" not in html.split("hero_aor")[0][-200:]

    html = report.build_report(study_cfg, include_video=False).read_text()
    assert "hero_aor" not in html                         # --no-video drops it

    html = report.build_report(study_cfg, max_video_mb=25).read_text()
    assert "data:video/mp4;base64" in html                # small enough -> inline
