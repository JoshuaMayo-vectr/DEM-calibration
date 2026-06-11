"""Phase-5 exit-criterion tests for calibration/render.py.

Headless snapshots must render with no GUI (PNG of the right size,
non-blank), the per-trial hook must produce both snapshot.png and
profile_fit.png, and the contact sheet must tile to exact grid dimensions
while surviving missing images. OVITO-dependent tests are skipped when the
ovito package is unavailable; the matplotlib fallback and the PIL contact
sheet are tested unconditionally.
"""

import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from calibration.render import (  # noqa: E402
    IMAGE_SIZE,
    LABEL_HEIGHT,
    _find_final_dump,
    _snapshot_matplotlib,
    contact_sheet,
    render_snapshot,
    render_trial,
)
from tests import synth  # noqa: E402

PHASE3_MED = REPO / "results" / "phase3-aor" / "med" / "post" / "med_final.liggghts"


def _cone_dump(tmp_path: Path, name: str = "t1_final.liggghts", n: int = 400) -> Path:
    df = synth.make_cone(25.0, np.random.default_rng(42), n=n)
    return synth.write_dump(df, tmp_path / name)


def _assert_png(path: Path, size: tuple[int, int] | None = None):
    assert path.exists()
    img = Image.open(path)
    if size is not None:
        assert img.size == size
    assert np.asarray(img.convert("L")).std() > 0  # non-blank


# ------------------------------------------------------------ ovito snapshot

def test_snapshot_synthetic(tmp_path):
    pytest.importorskip("ovito")
    dump = _cone_dump(tmp_path)
    out = render_snapshot(dump, tmp_path / "snap.png", label="t1", fallback="never")
    _assert_png(out, IMAGE_SIZE)


def test_snapshot_real_dump(tmp_path):
    pytest.importorskip("ovito")
    out = render_snapshot(PHASE3_MED, tmp_path / "med.png", fallback="never")
    _assert_png(out, IMAGE_SIZE)


# -------------------------------------------------------- matplotlib fallback

def test_matplotlib_fallback(tmp_path):
    dump = _cone_dump(tmp_path)
    out = _snapshot_matplotlib(dump, tmp_path / "fb.png", label="fb")
    _assert_png(out)


# ------------------------------------------------------------ per-trial hook

def test_render_trial(tmp_path):
    pytest.importorskip("ovito")
    trial = tmp_path / "trial"
    _cone_dump(trial / "post", "t1_final.liggghts")
    result = render_trial(trial)
    assert abs(result["aor_deg"] - 25.0) <= 1.0
    assert result["tag"] == "t1"
    _assert_png(trial / "snapshot.png", IMAGE_SIZE)
    _assert_png(trial / "profile_fit.png")
    assert result["snapshot_path"] == str(trial / "snapshot.png")


def test_find_final_dump_fallback(tmp_path):
    """A broken/killed trial without a _final dump must fall back to the
    highest-numbered timestep frame."""
    post = tmp_path / "post"
    _cone_dump(post, "t1_5000.liggghts")
    _cone_dump(post, "t1_120000.liggghts")
    assert _find_final_dump(tmp_path).name == "t1_120000.liggghts"


# ------------------------------------------------------------- contact sheet

def test_contact_sheet_dims(tmp_path):
    paths = []
    for i, size in enumerate([(800, 600), (400, 300), (640, 480)]):
        p = tmp_path / f"img{i}.png"
        Image.new("RGB", size, (200, 50 * i, 0)).save(p)
        paths.append((f"run{i}", p))
    paths.append(("dead", tmp_path / "does_not_exist.png"))  # must not raise

    out = contact_sheet(paths, tmp_path / "sheet.png", ncols=2, tile_width=400)
    img = Image.open(out)
    tile_h = round(400 * IMAGE_SIZE[1] / IMAGE_SIZE[0])
    assert img.size == (2 * 400, 2 * (tile_h + LABEL_HEIGHT))
    assert np.asarray(img.convert("L")).std() > 0
