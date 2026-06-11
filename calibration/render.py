"""Headless trial rendering for DEM calibration (Phase 5).

Renders a 3D snapshot PNG of a heap dump via the `ovito` pip package with no
GUI (offscreen Tachyon by default), wires the Phase-4 audit plot into a
per-trial `render_trial()` hook for the Phase-6 runner, and tiles N trials
into a single contact sheet for minute-scale skimming of an overnight batch.

Framing is FIXED (never zoom_all): every tile shares the same orthographic
camera and radius color scale, so a broken run — particles blown out of
frame, an empty floor, a pancake where a heap should be — is visually
obvious against its neighbours. If OVITO is unavailable or its renderer
fails, a matplotlib 3D-scatter fallback keeps batches alive.

CLI:
    .venv/bin/python calibration/render.py snapshot DUMP [--out PATH] [--label TEXT]
    .venv/bin/python calibration/render.py trial TRIAL_DIR [TRIAL_DIR ...] [--json]
    .venv/bin/python calibration/render.py sheet OUT.png TRIAL_DIR [TRIAL_DIR ...] [--ncols N]
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # before any ovito import

try:
    from calibration import measure
except ImportError:          # script execution: `python calibration/render.py`
    import measure

IMAGE_SIZE: tuple[int, int] = (800, 600)
CAMERA_DIR: tuple[float, float, float] = (2.0, 1.0, -0.7)   # oblique 3/4 view
CAMERA_POS: tuple[float, float, float] = (0.0, 0.0, 0.03)   # aimed at heap, not box
ORTHO_FOV: float = 0.085      # m; frames the largest credible heap (tuned on phase-3 runs)
RADIUS_RANGE: tuple[float, float] = (0.0017, 0.0020)  # m; fixed color scale across trials
TILE_WIDTH: int = 400
LABEL_HEIGHT: int = 26


# ------------------------------------------------------------ ovito snapshot

def _make_renderer():
    """Only place the renderer choice lives: Tachyon -> OSPRay -> OpenGL."""
    import ovito.vis as vis
    last_err: Exception | None = None
    for name in ("TachyonRenderer", "OSPRayRenderer", "OpenGLRenderer"):
        cls = getattr(vis, name, None)
        if cls is None:
            continue
        try:
            return cls()
        except Exception as err:  # renderer may fail to construct headless
            last_err = err
    raise RuntimeError(f"no usable OVITO renderer: {last_err}")


def _snapshot_ovito(dump_path: Path, out_path: Path, *, size: tuple[int, int]) -> None:
    from ovito.io import import_file
    from ovito.modifiers import ColorCodingModifier
    from ovito.vis import Viewport

    pipeline = import_file(str(dump_path))
    pipeline.modifiers.append(ColorCodingModifier(
        property="Radius",
        start_value=RADIUS_RANGE[0], end_value=RADIUS_RANGE[1]))
    pipeline.source.data.cell.vis.render_cell = False
    pipeline.add_to_scene()
    try:  # scene state is process-global — always detach, even on failure
        vp = Viewport(type=Viewport.Type.Ortho, camera_dir=CAMERA_DIR,
                      camera_pos=CAMERA_POS, fov=ORTHO_FOV)
        vp.render_image(filename=str(out_path), size=size,
                        renderer=_make_renderer(), background=(1, 1, 1))
    finally:
        pipeline.remove_from_scene()


def _snapshot_matplotlib(dump_path: str | Path, out_path: str | Path, *,
                         size: tuple[int, int] = IMAGE_SIZE,
                         label: str | None = None) -> Path:
    """Zero-dependency fallback: 3D scatter with the same fixed framing idea."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df = measure.read_dump(dump_path)
    dpi = 100
    fig = plt.figure(figsize=(size[0] / dpi, size[1] / dpi), dpi=dpi)
    ax = fig.add_subplot(projection="3d")
    ax.scatter(df["x"], df["y"], df["z"], c=df["radius"], s=2,
               vmin=RADIUS_RANGE[0], vmax=RADIUS_RANGE[1], cmap="viridis")
    ax.set_xlim(-0.14, 0.14)
    ax.set_ylim(-0.14, 0.14)
    ax.set_zlim(0.0, 0.20)
    ax.view_init(elev=12, azim=30)
    ax.set_axis_off()
    if label:
        ax.set_title(label, loc="left")
    fig.savefig(out_path, dpi=dpi)
    plt.close(fig)
    return out_path


def _stamp_label(image_path: Path, label: str) -> None:
    from PIL import Image, ImageDraw, ImageFont
    img = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=18)
    draw.text((10, 8), label, fill=(0, 0, 0), font=font)
    img.save(image_path)


def render_snapshot(dump_path: str | Path, out_path: str | Path | None = None, *,
                    size: tuple[int, int] = IMAGE_SIZE,
                    label: str | None = None,
                    fallback: str = "auto") -> Path:
    """Render one dump to a PNG, headless. Returns the written path.

    fallback: "auto" (matplotlib scatter if OVITO import/render fails),
    "never" (re-raise), or "force" (skip OVITO entirely).
    """
    dump_path = Path(dump_path)
    if out_path is None:
        out_path = dump_path.parent / f"{dump_path.stem}_snapshot.png"
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if fallback == "force":
        return _snapshot_matplotlib(dump_path, out_path, size=size, label=label)
    try:
        _snapshot_ovito(dump_path, out_path, size=size)
    except Exception as err:
        if fallback != "auto":
            raise
        print(f"WARNING: OVITO render failed ({err}); using matplotlib fallback",
              file=sys.stderr)
        return _snapshot_matplotlib(dump_path, out_path, size=size, label=label)
    if label:
        _stamp_label(out_path, label)
    return out_path


# ------------------------------------------------------------ per-trial hook

def _find_final_dump(trial_dir: str | Path) -> Path:
    """post/<tag>_final.liggghts, else the highest-numbered timestep dump.

    The fallback matters for broken/killed trials that never wrote a final
    frame — the Phase-6 runner still gets something to look at.
    """
    post = Path(trial_dir) / "post"
    finals = sorted(post.glob("*_final.liggghts"))
    if finals:
        return finals[0]
    numbered = [(int(m.group(1)), p) for p in post.glob("*.liggghts")
                if (m := re.search(r"_(\d+)\.liggghts$", p.name))]
    if not numbered:
        raise FileNotFoundError(f"no .liggghts dumps under {post}")
    return max(numbered)[1]


def render_trial(trial_dir: str | Path, *, tag: str | None = None) -> dict:
    """The Phase-6 rendering hook: snapshot.png + profile_fit.png per trial.

    Finds the final dump, renders trial_dir/snapshot.png, runs the Phase-4
    measurement (bulk density too when the settled pre-lift dump exists) with
    the audit plot routed to trial_dir/profile_fit.png. Returns the measure
    dict extended with snapshot_path and tag.
    """
    trial_dir = Path(trial_dir)
    final = _find_final_dump(trial_dir)
    if tag is None:
        tag = re.sub(r"_(final|\d+)$", "", final.stem)
    settled = trial_dir / "post" / f"{tag}_50000.liggghts"

    snapshot = render_snapshot(final, trial_dir / "snapshot.png", label=tag)
    result = measure.measure_heap(
        final,
        settled_dump=settled if settled.exists() else None,
        plot_path=trial_dir / "profile_fit.png")
    result["snapshot_path"] = str(snapshot)
    result["tag"] = tag
    return result


# ------------------------------------------------------------- contact sheet

def contact_sheet(items, out_path: str | Path, *,
                  ncols: int | None = None,
                  tile_width: int = TILE_WIDTH) -> Path:
    """Tile (label, image_path) pairs into one grid PNG. Never raises on a
    missing/unreadable image — that cell becomes a grey 'MISSING' tile, so
    one dead trial cannot kill the overnight-batch overview."""
    import math
    from PIL import Image, ImageDraw, ImageFont

    items = list(items)
    if not items:
        raise ValueError("contact_sheet needs at least one item")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if ncols is None:
        ncols = math.ceil(math.sqrt(len(items)))
    nrows = math.ceil(len(items) / ncols)
    tile_h = round(tile_width * IMAGE_SIZE[1] / IMAGE_SIZE[0])
    cell_h = tile_h + LABEL_HEIGHT
    font = ImageFont.load_default(size=14)

    sheet = Image.new("RGB", (ncols * tile_width, nrows * cell_h), (255, 255, 255))
    draw = ImageDraw.Draw(sheet)
    for i, (label, image_path) in enumerate(items):
        x0 = (i % ncols) * tile_width
        y0 = (i // ncols) * cell_h
        try:
            img = Image.open(image_path).convert("RGB")
            img.thumbnail((tile_width, tile_h))
            sheet.paste(img, (x0 + (tile_width - img.width) // 2,
                              y0 + (tile_h - img.height) // 2))
        except Exception:
            draw.rectangle([x0, y0, x0 + tile_width, y0 + tile_h], fill=(190, 190, 190))
            draw.text((x0 + 10, y0 + tile_h // 2), "MISSING", fill=(80, 0, 0), font=font)
        draw.rectangle([x0, y0 + tile_h, x0 + tile_width, y0 + cell_h], fill=(240, 240, 240))
        draw.text((x0 + 8, y0 + tile_h + 5), str(label), fill=(0, 0, 0), font=font)
        draw.rectangle([x0, y0, x0 + tile_width - 1, y0 + cell_h - 1],
                       outline=(200, 200, 200))
    sheet.save(out_path)
    return out_path


def _trial_label(trial_dir: Path) -> str:
    """'<tag>  AoR <x>°' from measured.json (Phase-6 contract) if present,
    else measured on the fly; 'AoR n/a' when measurement fails."""
    tag = trial_dir.name
    measured = trial_dir / "measured.json"
    try:
        if measured.exists():
            aor = json.loads(measured.read_text())["aor_deg"]
        else:
            aor = measure.measure_heap(
                _find_final_dump(trial_dir),
                plot_path=trial_dir / "profile_fit.png")["aor_deg"]
        return f"{tag}  AoR {aor:.1f}\N{DEGREE SIGN}"
    except Exception:
        return f"{tag}  AoR n/a"


# -------------------------------------------------------------- entry point

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    ap_snap = sub.add_parser("snapshot", help="render one dump to PNG")
    ap_snap.add_argument("dump", help="LIGGGHTS custom dump file")
    ap_snap.add_argument("--out", help="output PNG (default: alongside dump)")
    ap_snap.add_argument("--label", help="text stamped on the image")

    ap_trial = sub.add_parser("trial", help="snapshot + profile fit for trial dirs")
    ap_trial.add_argument("trial_dirs", nargs="+")
    ap_trial.add_argument("--json", action="store_true", help="print results as JSON")

    ap_sheet = sub.add_parser("sheet", help="tile trial snapshots into one image")
    ap_sheet.add_argument("out", help="output contact-sheet PNG")
    ap_sheet.add_argument("trial_dirs", nargs="+")
    ap_sheet.add_argument("--ncols", type=int, help="grid columns (default: ~sqrt(N))")

    args = ap.parse_args()

    if args.cmd == "snapshot":
        out = render_snapshot(args.dump, args.out, label=args.label)
        print(out)

    elif args.cmd == "trial":
        results = {}
        for d in args.trial_dirs:
            results[d] = render_trial(d)
            if not args.json:
                r = results[d]
                print(f"{d}: aor={r['aor_deg']:.2f} deg  snapshot={r['snapshot_path']}")
        if args.json:
            print(json.dumps(results, indent=2))

    elif args.cmd == "sheet":
        items: list[tuple[str, Path]] = []
        for d in args.trial_dirs:
            trial_dir = Path(d)
            snap = trial_dir / "snapshot.png"
            if not snap.exists():
                try:
                    snap = render_snapshot(_find_final_dump(trial_dir), snap,
                                           label=trial_dir.name)
                except Exception as err:
                    print(f"WARNING: could not render {d}: {err}", file=sys.stderr)
            items.append((_trial_label(trial_dir), snap))
        out = contact_sheet(items, args.out, ncols=args.ncols)
        print(out)


if __name__ == "__main__":
    main()
