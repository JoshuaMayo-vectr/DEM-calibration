"""Tests for calibration/video.py — frame selection, encoders, the turntable
end-to-end on a synthetic dump (matplotlib fallback, no OVITO needed), the
formation re-sim path with a stubbed engine, and the progress sidecar. No
LIGGGHTS, no real renders beyond tiny matplotlib frames."""

import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from calibration import runner, video  # noqa: E402
from tests import synth  # noqa: E402


def _frames(tmp_path, n=4, size=(64, 48)) -> list[Path]:
    out = []
    for i in range(n):
        p = tmp_path / f"f{i:04d}.png"
        Image.new("RGB", size, (10 * i, 20, 40)).save(p)
        out.append(p)
    return out


def _fake_trial(tmp_path, *, tag="aaaaaaaaaa_s1", steps=(), final=True,
                measured: dict | None = None) -> Path:
    trial = tmp_path / "cache" / "aaaaaaaaaa" / "seed1"
    (trial / "post").mkdir(parents=True)
    for s in steps:
        (trial / "post" / f"{tag}_{s}.liggghts").write_text("stub")
    if final:
        (trial / "post" / f"{tag}_final.liggghts").write_text("stub")
    if measured is not None:
        (trial / "measured.json").write_text(json.dumps({"tag": tag, **measured}))
    return trial


# ------------------------------------------------------------- orbit math
def test_orbit_dirs_shape():
    dirs = video._orbit_dirs(8)
    assert len(dirs) == 8
    for x, y, z in dirs:
        assert math.hypot(x, y) == pytest.approx(1.0)
        assert z == pytest.approx(-video.ORBIT_ELEV_RATIO)
    assert dirs[0] != dirs[4]                       # actually sweeps


# ------------------------------------------------------------- frame selection
def test_select_frames_formation_raises_on_pruned(tmp_path):
    trial = _fake_trial(tmp_path, steps=(50000,), measured={"aor_deg": 27.0})
    with pytest.raises(FileNotFoundError, match="pruned"):
        video.select_frames(trial, "formation", "aor")


def test_select_frames_formation_full_sequence(tmp_path):
    steps = tuple(range(0, 120000, 10000))
    trial = _fake_trial(tmp_path, steps=steps)
    frames = video.select_frames(trial, "formation", "aor")
    assert len(frames) == len(steps) + 1            # + final
    nums = [int(m.group(1)) for f in frames[:-1]
            if (m := __import__("re").search(r"_(\d+)\.liggghts$", f.name))]
    assert nums == sorted(nums)
    assert frames[-1].name.endswith("_final.liggghts")


def test_select_frames_flow_steady_only(tmp_path):
    steady = runner.RESPONSES["drum"]["steady_step"]
    steps = (100000, steady, steady + 25000)
    trial = _fake_trial(tmp_path, tag="drumbbbb_s1", steps=steps,
                        measured={"drum_aor_deg": 36.0})
    frames = video.select_frames(trial, "flow", "drum")
    names = [f.name for f in frames]
    assert f"drumbbbb_s1_{100000}.liggghts" not in names   # pre-steady dropped
    assert len(frames) == 3                                # 2 steady + final


def test_select_frames_turntable_needs_only_final(tmp_path):
    trial = _fake_trial(tmp_path, steps=())
    frames = video.select_frames(trial, "turntable", "aor")
    assert len(frames) == 1 and frames[0].name.endswith("_final.liggghts")


def test_infer_response():
    assert video.infer_response(Path("results/cache/abc123/seed1")) == "aor"
    assert video.infer_response(Path("results/cache/drum-abc/seed1")) == "drum"
    assert video.infer_response(Path("results/cache/drum45-abc/seed1")) == "drum45"


# ------------------------------------------------------------- encoders
def test_encode_gif(tmp_path):
    frames = _frames(tmp_path)
    out = video.encode_gif(frames, tmp_path / "v.gif", fps=8)
    assert out.exists() and out.stat().st_size > 0
    img = Image.open(out)
    img.seek(3)                                     # 4 frames present
    with pytest.raises(EOFError):
        img.seek(4)


def test_encode_mp4(tmp_path):
    pytest.importorskip("imageio_ffmpeg")
    frames = _frames(tmp_path)
    out = video.encode_mp4(frames, tmp_path / "v.mp4", fps=8)
    assert out.exists() and out.stat().st_size > 0


# ------------------------------------------------------------- end-to-end (no OVITO)
def test_render_movie_turntable_fallback(tmp_path):
    trial = tmp_path / "trial"
    (trial / "post").mkdir(parents=True)
    df = synth.make_cone(25.0, np.random.default_rng(7), n=120)
    synth.write_dump(df, trial / "post" / "t1_final.liggghts")

    out = video.render_movie(trial, kind="turntable", n_frames=4,
                             size=(160, 120), fallback="force")
    assert out.exists() and out.stat().st_size > 0
    prog = json.loads(video.progress_path(trial / "video_turntable.mp4").read_text())
    assert prog["stage"] == "done"
    assert prog["n_frames"] == 4 and prog["frame"] == 4
    assert not (trial / ".video_frames").exists()   # frames cleaned after encode


def test_render_movie_error_writes_progress(tmp_path):
    trial = _fake_trial(tmp_path, steps=(), final=False)   # nothing to render
    with pytest.raises(FileNotFoundError):
        video.render_movie(trial, kind="turntable", fallback="force")
    prog = json.loads(video.progress_path(trial / "video_turntable.mp4").read_text())
    assert prog["stage"] == "error" and prog["error"]


# ------------------------------------------------------------- formation re-sim
def test_formation_resim_path(tmp_path, monkeypatch):
    """A pruned aor dir + allow_resim: the stub engine writes the formation
    frames into the scratch, the movie encodes, the scratch is deleted, and
    the cache entry (measured.json) is byte-identical afterwards."""
    params = {"fric": 0.5, "rollfric": 0.12, "rest": 0.5}
    trial = _fake_trial(tmp_path, steps=(50000,),
                        measured={"aor_deg": 26.0, "params": params, "seed": 1})
    measured_before = (trial / "measured.json").read_bytes()

    df = synth.make_cone(25.0, np.random.default_rng(3), n=80)

    def fake_launch(canon, seed, scratch, tag, response="aor", *,
                    template=None, wall_limit=None):
        assert response == "aor" and seed == 1
        assert Path(scratch).name == "video_resim"
        for s in range(0, video.FORMATION_MIN_FRAMES * 1000, 1000):
            synth.write_dump(df, Path(scratch) / "post" / f"{tag}_{s}.liggghts")
        synth.write_dump(df, Path(scratch) / "post" / f"{tag}_final.liggghts")

    monkeypatch.setattr(video.runner, "_launch_sim", fake_launch)
    out = video.render_movie(trial, kind="formation", fallback="force",
                             size=(120, 90), allow_resim=True)
    assert out.exists() and out.stat().st_size > 0
    assert not (trial / "video_resim").exists()           # scratch reclaimed
    assert (trial / "measured.json").read_bytes() == measured_before
    prog = json.loads(video.progress_path(trial / "video_formation.mp4").read_text())
    assert prog["stage"] == "done"


def test_formation_without_resim_still_raises(tmp_path):
    trial = _fake_trial(tmp_path, steps=(50000,),
                        measured={"aor_deg": 26.0,
                                  "params": {"fric": 0.5, "rollfric": 0.1},
                                  "seed": 1})
    with pytest.raises(FileNotFoundError):
        video.render_movie(trial, kind="formation", fallback="force",
                           allow_resim=False)


# ------------------------------------------------------------- CLI smoke
def test_cli_help_and_args(capsys, monkeypatch):
    for argv in (["video.py", "movie", "--help"], ["video.py", "hero", "--help"]):
        monkeypatch.setattr(sys, "argv", argv)
        with pytest.raises(SystemExit) as exc:
            video.main()
        assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "--kind" in out and "--config" in out


def test_parse_size_rejects_odd():
    import argparse
    with pytest.raises(argparse.ArgumentTypeError):
        video._parse_size("801x600")
    assert video._parse_size("640x480") == (640, 480)
