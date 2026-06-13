"""Trial videos for the calibration cockpit (Phase 8.5 premium).

Three kinds, matched to what the dump-pruning policy leaves on disk:

  flow        drum/drum45 — the steady-state frames SURVIVE pruning (17–36
              dumps), so the avalanching bed renders post-hoc anytime.
  turntable   aor — a 360° camera orbit of the final heap. Needs only the
              final dump (always kept) → available for every trial ever run.
  formation   aor — the full pour-settle-lift sequence (~150 frames). Those
              intermediates are PRUNED after measurement, so post-hoc this
              re-runs the one simulation (~4 min) into a scratch dir inside
              the seed dir, renders, encodes, and deletes the scratch — the
              shared cache entry (measured.json, snapshot, pruned dumps) is
              never touched.

OVITO renders the frames (Tachyon → OSPRay → OpenGL, matplotlib-scatter
fallback) on the dark cockpit background; imageio-ffmpeg encodes H.264 MP4
(Pillow GIF if ffmpeg is unavailable). OVITO is NOT thread-safe and Streamlit
runs scripts on worker threads, so the UI must never import-and-call this in
process: ui_state.start_video/start_hero spawn the CLI detached, and the
<out>.progress.json sidecar (atomic tmp+rename) is how the UI watches a
render without touching the process.

`hero` renders the showcase pair for a finished study's best trial —
formation for aor, flow for the drum — and copies them into the study dir as
hero_aor.mp4 / hero_drum.mp4 (so study + report stay self-contained).
optimize.py spawns it automatically at end of run (--no-hero opts out).

CLI:
    .venv/bin/python calibration/video.py movie TRIAL_DIR --kind flow|turntable|formation
        [--response aor|drum|drum45] [--fps 12] [--frames 48] [--size 800x600]
        [--out PATH] [--fallback auto|never|force]
    .venv/bin/python calibration/video.py hero --config CONFIG [--force] [--fps 12]
"""

import argparse
import json
import math
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # before any ovito import

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

try:
    from calibration import render, runner
except ImportError:          # script execution: `python calibration/video.py`
    import render
    import runner

KINDS = ("flow", "turntable", "formation")
FPS_DEFAULT = 12
SIZE_DEFAULT: tuple[int, int] = (800, 600)   # even dims — yuv420p requirement
TURNTABLE_FRAMES = 48                        # 4 s loop at 12 fps
# heap preset elevation: CAMERA_DIR (2,1,-0.7) -> z/|xy| = 0.7/sqrt(5) ~ 0.31
ORBIT_ELEV_RATIO = 0.31
FORMATION_MIN_FRAMES = 10                    # fewer numbered dumps = pruned dir
BACKGROUND = (0.043, 0.071, 0.125)           # ui_theme bg #0B1220 — seamless tiles

# kinds that make sense per response (the UI reads this for its buttons)
KINDS_BY_RESPONSE = {"aor": ("turntable", "formation"),
                     "drum": ("flow",), "drum45": ("flow",)}


# ------------------------------------------------------------- progress sidecar

def progress_path(out_path: Path) -> Path:
    return Path(out_path).with_name(Path(out_path).name + ".progress.json")


def movie_match(trial_dir: Path) -> str:
    """Substring a `ps -o command=` line carries for this render — the
    PID-reuse guard (macOS rewrites argv[0], so match on the arguments)."""
    return f"video.py movie {trial_dir}"


def hero_match(config: Path) -> str:
    return f"video.py hero --config {config}"


class _Progress:
    """Atomic progress sidecar the UI polls. Stages: start → simulate? →
    frames → encode → done | error."""

    def __init__(self, out_path: Path, match: str):
        self.path = progress_path(out_path)
        self.state = {"pid": os.getpid(), "match": match, "out": str(out_path),
                      "stage": "start", "frame": 0, "n_frames": 0, "error": None,
                      "started": _now(), "updated": _now()}
        self._flush()

    def update(self, **kw) -> None:
        self.state.update(kw)
        self.state["updated"] = _now()
        self._flush()

    def _flush(self) -> None:
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(self.state, indent=2))
        tmp.rename(self.path)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ------------------------------------------------------------- frame selection

def _numbered_dumps(post: Path, tag: str | None) -> list[Path]:
    out = []
    for p in post.glob("*.liggghts"):
        m = re.search(r"_(\d+)\.liggghts$", p.name)
        if m and (tag is None or p.name.startswith(f"{tag}_")):
            out.append((int(m.group(1)), p))
    return [p for _, p in sorted(out)]


def _tag_for(trial_dir: Path) -> str | None:
    """The dump tag: measured.json carries it (Phase-6 contract); a scratch
    re-sim dir has no measured.json, so fall back to the final-dump stem."""
    mj = Path(trial_dir) / "measured.json"
    if mj.exists():
        try:
            tag = json.loads(mj.read_text()).get("tag")
            if tag:
                return tag
        except (json.JSONDecodeError, OSError):
            pass
    try:
        final = render.find_final_dump(trial_dir)
    except FileNotFoundError:
        return None
    return re.sub(r"_(final|\d+)$", "", final.stem)


def select_frames(trial_dir: Path, kind: str, response: str = "aor") -> list[Path]:
    """The dump sequence a video of `kind` renders, in temporal order.
    Raises FileNotFoundError when the dir can't supply it (notably: a pruned
    aor dir for kind='formation' — the re-sim path exists for that)."""
    trial_dir = Path(trial_dir)
    post = trial_dir / "post"
    tag = _tag_for(trial_dir)

    if kind == "turntable":
        return [render.find_final_dump(trial_dir)]

    if kind == "flow":
        steady = runner.RESPONSES[response].get("steady_step")
        if steady is None:
            raise ValueError(f"flow video needs a drum-like response, got {response!r}")
        frames = render.steady_frames(trial_dir, tag, steady) if tag else []
        if not frames:
            frames = _numbered_dumps(post, tag)
        final = post / f"{tag}_final.liggghts" if tag else None
        if final and final.exists():
            frames = list(frames) + [final]
        if not frames:
            raise FileNotFoundError(f"no dump frames under {post}")
        return frames

    if kind == "formation":
        frames = _numbered_dumps(post, tag)
        final = post / f"{tag}_final.liggghts" if tag else None
        if final and final.exists():
            frames.append(final)
        if len(frames) < FORMATION_MIN_FRAMES:
            raise FileNotFoundError(
                f"only {len(frames)} dump frames under {post} — the formation "
                "sequence was pruned; re-simulate (CLI/UI do this automatically)")
        return frames

    raise ValueError(f"unknown kind {kind!r} (have {KINDS})")


def _orbit_dirs(n: int) -> list[tuple[float, float, float]]:
    """n camera directions sweeping a full turn at the heap preset's elevation."""
    return [(math.cos(2 * math.pi * i / n), math.sin(2 * math.pi * i / n),
             -ORBIT_ELEV_RATIO) for i in range(n)]


def _camera_for(kind: str, response: str) -> tuple[tuple, tuple, float]:
    if kind != "turntable" and response in ("drum", "drum45"):
        return (render.DRUM_CAMERA_DIR, render.DRUM_CAMERA_POS, render.DRUM_ORTHO_FOV)
    return (render.CAMERA_DIR, render.CAMERA_POS, render.ORTHO_FOV)


# ------------------------------------------------------------- frame rendering

def _radius_range_of(dump: Path) -> tuple[float, float]:
    """Color scale from the dump itself — material-agnostic by construction
    (wheat dumps span exactly the legacy constant; a custom PSD gets its own
    fixed scale, constant across the video's frames)."""
    try:
        from calibration import measure
    except ImportError:
        import measure
    r = measure.read_dump(dump)["radius"]
    lo, hi = float(r.min()), float(r.max())
    if lo == hi:
        lo, hi = lo * 0.95, hi * 1.05
    return (lo, hi)


def _render_frames_ovito(dumps: list[Path], frames_dir: Path, *,
                         camera_dirs: list[tuple], camera_pos: tuple, fov: float,
                         size: tuple[int, int], progress: "_Progress") -> list[Path]:
    """One pipeline build, N renders. Single dump + many camera_dirs = orbit;
    many dumps + one camera_dir = time series (frame order = list order)."""
    from ovito.io import import_file
    from ovito.modifiers import ColorCodingModifier
    from ovito.vis import Viewport

    rr = _radius_range_of(dumps[-1])
    src = [str(d) for d in dumps] if len(dumps) > 1 else str(dumps[0])
    pipeline = import_file(src)
    pipeline.modifiers.append(ColorCodingModifier(
        property="Radius", start_value=rr[0], end_value=rr[1]))
    pipeline.source.data.cell.vis.render_cell = False
    pipeline.add_to_scene()
    try:
        renderer = render._make_renderer()
        paths: list[Path] = []
        if len(dumps) == 1:
            for i, cdir in enumerate(camera_dirs):
                vp = Viewport(type=Viewport.Type.Ortho, camera_dir=cdir,
                              camera_pos=camera_pos, fov=fov)
                out = frames_dir / f"f{i:04d}.png"
                vp.render_image(filename=str(out), size=size,
                                renderer=renderer, background=BACKGROUND)
                paths.append(out)
                progress.update(stage="frames", frame=i + 1)
        else:
            vp = Viewport(type=Viewport.Type.Ortho, camera_dir=camera_dirs[0],
                          camera_pos=camera_pos, fov=fov)
            for i in range(len(dumps)):
                out = frames_dir / f"f{i:04d}.png"
                vp.render_image(filename=str(out), frame=i, size=size,
                                renderer=renderer, background=BACKGROUND)
                paths.append(out)
                progress.update(stage="frames", frame=i + 1)
        return paths
    finally:
        pipeline.remove_from_scene()


def _render_frames_matplotlib(dumps: list[Path], frames_dir: Path, *,
                              n_orbit: int, size: tuple[int, int],
                              progress: "_Progress") -> list[Path]:
    """Zero-OVITO fallback, same shape as the real thing: an azimuth sweep for
    the single-dump orbit, the fixed Phase-5 framing for time series."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    try:
        from calibration import measure
    except ImportError:
        import measure

    paths: list[Path] = []
    if len(dumps) == 1:
        df = measure.read_dump(dumps[0])
        rr = _radius_range_of(dumps[0])
        dpi = 100
        for i in range(n_orbit):
            fig = plt.figure(figsize=(size[0] / dpi, size[1] / dpi), dpi=dpi)
            ax = fig.add_subplot(projection="3d")
            ax.scatter(df["x"], df["y"], df["z"], c=df["radius"], s=2,
                       vmin=rr[0], vmax=rr[1], cmap="viridis")
            ax.set_xlim(-0.14, 0.14)
            ax.set_ylim(-0.14, 0.14)
            ax.set_zlim(0.0, 0.20)
            ax.view_init(elev=18, azim=360.0 * i / n_orbit)
            ax.set_axis_off()
            fig.patch.set_facecolor("#0B1220")
            out = frames_dir / f"f{i:04d}.png"
            fig.savefig(out, dpi=dpi, facecolor=fig.get_facecolor())
            plt.close(fig)
            paths.append(out)
            progress.update(stage="frames", frame=i + 1)
    else:
        for i, dump in enumerate(dumps):
            out = frames_dir / f"f{i:04d}.png"
            render._snapshot_matplotlib(dump, out, size=size)
            paths.append(out)
            progress.update(stage="frames", frame=i + 1)
    return paths


def _render_frames(dumps, frames_dir, *, camera_dirs, camera_pos, fov, size,
                   fallback, progress) -> list[Path]:
    if fallback == "force":
        return _render_frames_matplotlib(dumps, frames_dir,
                                         n_orbit=len(camera_dirs), size=size,
                                         progress=progress)
    try:
        return _render_frames_ovito(dumps, frames_dir, camera_dirs=camera_dirs,
                                    camera_pos=camera_pos, fov=fov, size=size,
                                    progress=progress)
    except Exception as err:  # noqa: BLE001 — renderer trouble must not kill the video
        if fallback != "auto":
            raise
        print(f"WARNING: OVITO frame render failed ({err}); matplotlib fallback",
              file=sys.stderr)
        return _render_frames_matplotlib(dumps, frames_dir,
                                         n_orbit=len(camera_dirs), size=size,
                                         progress=progress)


# ------------------------------------------------------------- encoding

def encode_mp4(frames: list[Path], out_path: Path, fps: int = FPS_DEFAULT) -> Path:
    """H.264 via imageio-ffmpeg's bundled binary (no brew dependency).
    macro_block_size=1 keeps the exact frame dims (even-sized by contract)."""
    import imageio.v2 as imageio

    out_path = Path(out_path)
    writer = imageio.get_writer(str(out_path), fps=fps, codec="libx264",
                                quality=7, pixelformat="yuv420p",
                                macro_block_size=1)
    try:
        for f in frames:
            writer.append_data(imageio.imread(str(f)))
    finally:
        writer.close()
    return out_path


def encode_gif(frames: list[Path], out_path: Path, fps: int = FPS_DEFAULT) -> Path:
    """Pillow-only fallback — works on a machine where the ffmpeg wheel doesn't."""
    from PIL import Image

    out_path = Path(out_path)
    imgs = [Image.open(f).convert("P", palette=Image.Palette.ADAPTIVE)
            for f in frames]
    imgs[0].save(out_path, save_all=True, append_images=imgs[1:],
                 duration=int(1000 / fps), loop=0)
    return out_path


# ------------------------------------------------------------- public API

def _params_from_measured(trial_dir: Path) -> tuple[dict, int, dict | None]:
    mj = Path(trial_dir) / "measured.json"
    if not mj.exists():
        raise FileNotFoundError(
            f"no measured.json in {trial_dir} — cannot recover params for a re-sim")
    data = json.loads(mj.read_text())
    if not data.get("params") or data.get("seed") is None:
        raise ValueError(f"measured.json in {trial_dir} lacks params/seed")
    return data["params"], int(data["seed"]), data.get("material")


def formation_resim(params: dict, seed: int, *, response: str = "aor",
                    scratch: Path, material: dict | None = None) -> Path:
    """Re-run ONE simulation into a scratch dir to regenerate the pruned
    formation frames. Zero cache impact: nothing here writes measured.json,
    and the scratch lives inside the seed dir where _cached/_prune never look.
    `material` (from the trial's measured.json) reproduces the exact physics —
    a custom-material trial re-renders its template variant. The caller
    deletes the scratch after encoding (~150 frames ≈ 2 GB)."""
    canon = runner.canonical(params, response)
    mat = runner.material_canon(material)
    tag = runner._tag(canon, seed, response, mat)
    scratch = Path(scratch)
    shutil.rmtree(scratch, ignore_errors=True)
    (scratch / "post").mkdir(parents=True)
    template = (runner._render_template(response, mat, scratch)
                if mat is not None else None)
    runner._launch_sim(canon, seed, scratch, tag, response, template=template,
                       wall_limit=runner._scaled_wall_limit(response, mat))
    return scratch


def render_movie(trial_dir: Path, *, kind: str, response: str = "aor",
                 out_path: Path | None = None, fps: int = FPS_DEFAULT,
                 size: tuple[int, int] = SIZE_DEFAULT,
                 n_frames: int = TURNTABLE_FRAMES, fallback: str = "auto",
                 allow_resim: bool = False) -> Path:
    """Render one trial video; returns the artifact path (.mp4, or .gif when
    ffmpeg is unavailable). Writes <out>.progress.json throughout. A pruned
    formation sequence raises FileNotFoundError unless allow_resim=True, in
    which case the one simulation re-runs first (~4 min, scratch-dir only)."""
    trial_dir = Path(trial_dir)
    if kind not in KINDS:
        raise ValueError(f"unknown kind {kind!r} (have {KINDS})")
    out_path = Path(out_path) if out_path is not None else trial_dir / f"video_{kind}.mp4"
    progress = _Progress(out_path, movie_match(trial_dir))

    scratch: Path | None = None
    try:
        try:
            dumps = select_frames(trial_dir, kind, response)
        except FileNotFoundError:
            if kind != "formation" or not allow_resim:
                raise
            params, seed, material = _params_from_measured(trial_dir)
            progress.update(stage="simulate")
            scratch = trial_dir / "video_resim"
            formation_resim(params, seed, response=response, scratch=scratch,
                            material=material)
            dumps = select_frames(scratch, kind, response)

        camera_dir, camera_pos, fov = _camera_for(kind, response)
        camera_dirs = _orbit_dirs(n_frames) if kind == "turntable" else [camera_dir]
        total = len(camera_dirs) if kind == "turntable" else len(dumps)
        progress.update(stage="frames", frame=0, n_frames=total)

        frames_dir = trial_dir / ".video_frames"
        shutil.rmtree(frames_dir, ignore_errors=True)
        frames_dir.mkdir(parents=True)
        try:
            frame_paths = _render_frames(
                dumps, frames_dir, camera_dirs=camera_dirs,
                camera_pos=camera_pos, fov=fov, size=size,
                fallback=fallback, progress=progress)
            progress.update(stage="encode")
            try:
                artifact = encode_mp4(frame_paths, out_path, fps=fps)
            except (ImportError, OSError, RuntimeError, ValueError) as err:
                print(f"WARNING: mp4 encode failed ({err}); writing GIF",
                      file=sys.stderr)
                artifact = encode_gif(frame_paths, out_path.with_suffix(".gif"),
                                      fps=fps)
        finally:
            shutil.rmtree(frames_dir, ignore_errors=True)
        progress.update(stage="done", out=str(artifact))
        return artifact
    except BaseException as err:
        progress.update(stage="error", error=f"{type(err).__name__}: {err}")
        raise
    finally:
        if scratch is not None:
            shutil.rmtree(scratch, ignore_errors=True)


# ------------------------------------------------------------- hero

HERO_KIND = {"aor": "formation", "drum": "flow", "drum45": "flow"}


def hero(config_path: Path, *, force: bool = False, fps: int = FPS_DEFAULT,
         fallback: str = "auto") -> dict:
    """Showcase videos for a finished study's best trial: hero_<response>.mp4
    in the study dir, one per enabled response (formation for aor, flow for
    drums). Idempotent — existing artifacts are skipped unless --force, so the
    optimizer's end-of-run spawn can fire on every run/resume."""
    try:
        from calibration import optimize
    except ImportError:
        import optimize

    config_path = Path(config_path)
    cfg = optimize.load_config(config_path)
    outdir = Path(cfg.outdir)
    if not cfg.best_json.exists():
        raise FileNotFoundError(f"no best.json in {outdir} — run or plot first")
    payload = json.loads(cfg.best_json.read_text())
    best = payload.get("best") or {}
    if not best:
        raise ValueError("best.json holds no completed trial")

    progress = _Progress(outdir / "hero.mp4", hero_match(config_path))
    progress.update(stage="start", videos={})
    videos: dict[str, str | None] = {}
    try:
        for response in cfg.enabled_responses():
            hero_path = outdir / f"hero_{response}.mp4"
            existing = _existing_artifact(hero_path)
            if existing and not force:
                videos[response] = str(existing)
                continue
            h = best.get(optimize._hash_attr(response))
            if not h:
                videos[response] = None
                continue
            prefix = runner.RESPONSES[response]["dir_prefix"]
            trial_dir = runner.CACHE / f"{prefix}{h}" / f"seed{runner.SEEDS[0]}"
            if not trial_dir.exists():
                videos[response] = None
                continue
            progress.update(stage=f"render:{response}", videos=videos)
            artifact = render_movie(trial_dir, kind=HERO_KIND[response],
                                    response=response, fps=fps,
                                    fallback=fallback, allow_resim=True)
            target = hero_path.with_suffix(artifact.suffix)
            shutil.copy2(artifact, target)
            videos[response] = str(target)
        progress.update(stage="done", videos=videos)
        return videos
    except BaseException as err:
        progress.update(stage="error", error=f"{type(err).__name__}: {err}",
                        videos=videos)
        raise


def _existing_artifact(mp4_path: Path) -> Path | None:
    for p in (mp4_path, mp4_path.with_suffix(".gif")):
        if p.exists():
            return p
    return None


def infer_response(trial_dir: Path) -> str:
    """Response from the cache layout: results/cache/<prefix><hash>/seed<s>."""
    name = Path(trial_dir).parent.name
    if name.startswith("drum45-"):
        return "drum45"
    if name.startswith("drum-"):
        return "drum"
    return "aor"


# ------------------------------------------------------------- entry point

def _parse_size(text: str) -> tuple[int, int]:
    w, h = (int(x) for x in text.lower().split("x"))
    if w % 2 or h % 2:
        raise argparse.ArgumentTypeError("size must be even (yuv420p)")
    return (w, h)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    mv = sub.add_parser("movie", help="render one trial video")
    mv.add_argument("trial_dir")
    mv.add_argument("--kind", choices=KINDS, required=True)
    mv.add_argument("--response", choices=sorted(runner.RESPONSES), default=None,
                    help="default: inferred from the cache dir prefix")
    mv.add_argument("--fps", type=int, default=FPS_DEFAULT)
    mv.add_argument("--frames", type=int, default=TURNTABLE_FRAMES,
                    help="turntable orbit frame count")
    mv.add_argument("--size", type=_parse_size, default=SIZE_DEFAULT,
                    help="WxH, even dims (default 800x600)")
    mv.add_argument("--out", default=None)
    mv.add_argument("--fallback", choices=["auto", "never", "force"], default="auto")

    hr = sub.add_parser("hero", help="best-trial showcase videos for a study")
    hr.add_argument("--config", required=True)
    hr.add_argument("--force", action="store_true",
                    help="re-render even if hero videos exist")
    hr.add_argument("--fps", type=int, default=FPS_DEFAULT)
    hr.add_argument("--fallback", choices=["auto", "never", "force"], default="auto")

    args = ap.parse_args()
    if args.cmd == "movie":
        response = args.response or infer_response(args.trial_dir)
        out = render_movie(Path(args.trial_dir), kind=args.kind, response=response,
                           out_path=Path(args.out) if args.out else None,
                           fps=args.fps, size=args.size, n_frames=args.frames,
                           fallback=args.fallback, allow_resim=True)
        print(out)
    elif args.cmd == "hero":
        videos = hero(Path(args.config), force=args.force, fps=args.fps,
                      fallback=args.fallback)
        print(json.dumps(videos, indent=2))


if __name__ == "__main__":
    main()
