"""Phase-9 drawdown discrimination probe — does orifice flow rate vary along
the friction valley where the drum could not?

Standalone mini-runner (no cache, no registry — this is a probe; the response
graduates to runner.RESPONSES only if it discriminates). Launches the
drawdown template at the 9 valley anchors x N seeds in parallel, measures the
mass-flow rate from each log, and reports span / monotonicity vs the
seed-noise estimate. No physical target needed: the question is purely
whether the response SEPARATES valley members (its target would be sourced
afterwards, only if it does).

CLI:
    .venv/bin/python calibration/drawdown_probe.py run [--seeds 2] [--jobs N]
    .venv/bin/python calibration/drawdown_probe.py report
"""

import argparse
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from calibration import measure, runner  # noqa: E402
from calibration.valley_check import VALLEY_POINTS  # noqa: E402

OUTDIR = REPO_ROOT / "results" / "phase9-drum" / "drawdown-probe"
CSV = OUTDIR / "drawdown_probe.csv"
PLOT = OUTDIR / "drawdown_probe.png"
VERDICT = OUTDIR / "drawdown_verdict.json"

TEMPLATE = REPO_ROOT / "templates" / "drawdown.in"
MESHES = {
    "MESH": REPO_ROOT / "templates" / "meshes" / "cylinder_r0.040_h0.100.stl",
    "FLOORMESH": REPO_ROOT / "templates" / "meshes" / "floor_annulus_r0.046_o0.011.stl",
    "PLUGMESH": REPO_ROOT / "templates" / "meshes" / "plug_disk_r0.0135.stl",
    "CATCHMESH": REPO_ROOT / "templates" / "meshes" / "catch_disk_r0.030.stl",
}
WALL_LIMIT = 600  # s; runs take ~140 s


def _run_one(point: dict, seed: int) -> dict:
    """Launch one drawdown sim in its own dir; return measured flow rate."""
    tag = f"dd{runner.params_hash(point)}_s{seed}"
    rundir = OUTDIR / "runs" / tag
    log = rundir / f"log.{tag}"
    if not log.exists():  # poor man's cache: a finished log is reused
        (rundir / "post").mkdir(parents=True, exist_ok=True)
        argv = [runner.MPIRUN, "-np", str(runner.NRANKS), str(runner.LMP),
                "-in", str(TEMPLATE), "-var", "TAG", tag,
                "-var", "SEED", str(seed)]
        for var, p in MESHES.items():
            argv += ["-var", var, os.path.relpath(p, rundir)]
        canon = runner.canonical(point)
        for var in ("FRIC", "FRICPW", "ROLLFRIC", "ROLLFRICPW", "REST"):
            argv += ["-var", var, f"{canon[var.lower()]}"]
        argv += ["-log", f"log.{tag}"]
        with open(rundir / "run.out", "wb") as out:
            subprocess.run(argv, cwd=str(rundir), stdin=subprocess.DEVNULL,
                           stdout=out, stderr=subprocess.STDOUT,
                           timeout=WALL_LIMIT, check=True)
    res = measure.measure_drawdown(log, plot_path=rundir / "flow_fit.png")
    return {**point, "seed": seed, **{k: res[k] for k in
            ("flow_rate_kgs", "fit_r2", "crossed_mass_kg")},
            "warnings": "; ".join(res["warnings"])}


def run_probe(*, n_seeds: int = 2, jobs: int | None = None) -> pd.DataFrame:
    seeds = runner.SEEDS[:n_seeds]
    jobspec = [(p, s) for p in VALLEY_POINTS for s in seeds]
    with ThreadPoolExecutor(max_workers=runner._resolve_jobs(jobs)) as pool:
        rows = list(pool.map(lambda j: _run_one(*j), jobspec))
    df = pd.DataFrame(rows)
    agg = df.groupby(["fric", "rollfric", "rest"], as_index=False).agg(
        flow_gs=("flow_rate_kgs", lambda v: 1e3 * v.mean()),
        flow_gs_std=("flow_rate_kgs", lambda v: 1e3 * v.std(ddof=1)),
        fit_r2=("fit_r2", "median"))
    return agg.sort_values("fric").reset_index(drop=True)


def verdict(df: pd.DataFrame) -> dict:
    span = float(df["flow_gs"].max() - df["flow_gs"].min())
    noise = float(np.nanmedian(df["flow_gs_std"]))
    rho = float(df["fric"].corr(df["flow_gs"], method="spearman"))
    # discriminates if the span dwarfs seed noise and tracks fric
    go = bool(span >= 5 * max(noise, 1e-9) and abs(rho) >= 0.8)
    return {
        "n_points": int(len(df)),
        "flow_span_gs": span,
        "seed_noise_gs": noise,
        "span_over_noise": span / noise if noise > 0 else None,
        "spearman_fric_vs_flow": rho,
        "flow_min_gs": float(df["flow_gs"].min()),
        "flow_max_gs": float(df["flow_gs"].max()),
        "go": go,
        "criterion": "span >= 5x seed noise AND |spearman| >= 0.8",
    }


def make_plot(df: pd.DataFrame, out_path: Path = PLOT) -> Path:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(7, 5))
    ax.errorbar(df["fric"], df["flow_gs"], yerr=df["flow_gs_std"], fmt="o-",
                c="tab:red", capsize=3)
    for _, r in df.iterrows():
        ax.annotate(f"μr {r['rollfric']:.2f}", (r["fric"], r["flow_gs"]),
                    textcoords="offset points", xytext=(4, -10), fontsize=7)
    ax.set_xlabel("sliding friction μ_s (along the static-AoR valley)")
    ax.set_ylabel("orifice mass-flow rate  [g/s]")
    ax.set_title("drawdown probe — flow rate along the friction valley")
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=140)
    plt.close(fig)
    return out_path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    rn = sub.add_parser("run")
    rn.add_argument("--seeds", type=int, default=2)
    rn.add_argument("--jobs", type=int)
    sub.add_parser("report")
    args = ap.parse_args()

    OUTDIR.mkdir(parents=True, exist_ok=True)
    if args.cmd == "run":
        df = run_probe(n_seeds=args.seeds, jobs=args.jobs)
        df.to_csv(CSV, index=False)
    else:
        df = pd.read_csv(CSV)
    v = verdict(df)
    VERDICT.write_text(json.dumps(v, indent=2))
    make_plot(df)
    print(df.to_string(index=False))
    print(json.dumps(v, indent=2))
    print("VERDICT:", "DISCRIMINATES — graduate drawdown to a full response"
          if v["go"] else "no discrimination — the family closure stands")


if __name__ == "__main__":
    main()
