"""Phase-9 degeneracy-break verification (M4) — the go/no-go before optimizing.

The Phase-8 friction valley: parameter sets from fric 0.25 to 0.60 (rollfric
anti-correlated, 0.25 -> 0.11) all match the static AoR target — a single
response cannot pin sliding friction. This script runs the NEW drum response
at 9 cached in-band valley anchors and asks: does the drum angle actually
discriminate along the valley?

Go criterion: drum angle varies monotonically by >> sigma_drum (3.1 deg) and
the noise floor across the swept fric range, and the 36.17 deg target is
reachable. No-go: span < ~1.5 deg -> the drum cannot break the degeneracy;
stop and revisit model form (drawdown / multisphere) BEFORE optimizer compute.

The static AoR values come free from the Phase 7/8 cache; only the 18 drum
sims (9 points x 2 seeds) run live (~45-60 min). The results double as the
multi-response seed set for the Phase-9 optimizer.

CLI:
    .venv/bin/python calibration/valley_check.py run [--seeds 2] [--jobs N]
    .venv/bin/python calibration/valley_check.py report   # re-plot from CSV
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from calibration import render, runner  # noqa: E402

OUTDIR = REPO_ROOT / "results" / "phase9-drum"
CSV = OUTDIR / "valley_check.csv"
PLOT = OUTDIR / "valley_check.png"
SHEET = OUTDIR / "valley_contact_sheet.png"
VERDICT = OUTDIR / "valley_verdict.json"

TARGET_AOR, SIGMA_AOR = 27.0, 1.5
TARGET_DRUM, SIGMA_DRUM = 36.17, 3.1

# 9 in-band valley anchors spanning the fric axis, all with cached static-AoR
# results (Phase-7 LHS rows + Phase-8 GP trials incl. the trial-47 best at the
# fric=0.60 search edge). canonical() re-rounds to 4 dp, so these hit the
# existing cache exactly.
VALLEY_POINTS = [
    {"fric": 0.2477, "rollfric": 0.2249, "rest": 0.4945},
    {"fric": 0.2652, "rollfric": 0.2330, "rest": 0.7000},
    {"fric": 0.2955, "rollfric": 0.1622, "rest": 0.4414},
    {"fric": 0.3315, "rollfric": 0.1708, "rest": 0.7000},
    {"fric": 0.3545, "rollfric": 0.1754, "rest": 0.6070},
    {"fric": 0.4001, "rollfric": 0.1374, "rest": 0.5762},
    {"fric": 0.4499, "rollfric": 0.1425, "rest": 0.3053},
    {"fric": 0.5874, "rollfric": 0.1203, "rest": 0.4523},
    {"fric": 0.6000, "rollfric": 0.1203, "rest": 0.7000},
]


def run_check(*, n_seeds: int = 2, jobs: int | None = None) -> pd.DataFrame:
    """Evaluate both responses at every valley anchor (aor from cache, drum
    live) and return the tidy one-row-per-anchor frame."""
    aor_res = runner.evaluate_batch(VALLEY_POINTS, n_seeds=n_seeds, jobs=jobs,
                                    response="aor")
    drum_res = runner.evaluate_batch(VALLEY_POINTS, n_seeds=n_seeds, jobs=jobs,
                                     response="drum")
    rows = []
    for p, a, d in zip(VALLEY_POINTS, aor_res, drum_res):
        rows.append({
            **p,
            "aor": a["aor"], "aor_std": a["aor_std"], "aor_n_ok": a["n_ok"],
            "drum_aor": d["drum_aor"], "drum_aor_std": d["drum_aor_std"],
            "drum_frame_std": d["drum_frame_std"], "drum_n_ok": d["n_ok"],
            "drum_trial": d["trial_dirs"][0],
        })
    return pd.DataFrame(rows)


def verdict(df: pd.DataFrame, *, noise_floor: float | None = None) -> dict:
    """The go/no-go numbers: span, monotonicity, target reachability."""
    ok = df.dropna(subset=["drum_aor"]).sort_values("fric")
    span = float(ok["drum_aor"].max() - ok["drum_aor"].min())
    rho = float(ok["fric"].corr(ok["drum_aor"], method="spearman"))
    lo, hi = TARGET_DRUM - SIGMA_DRUM, TARGET_DRUM + SIGMA_DRUM
    n_inband = int(((ok["drum_aor"] >= lo) & (ok["drum_aor"] <= hi)).sum())
    reachable = bool(ok["drum_aor"].max() >= lo)
    go = bool(span >= 3.0 and abs(rho) >= 0.8 and reachable)
    return {
        "n_points": int(len(ok)),
        "drum_span_deg": span,
        "spearman_fric_vs_drum": rho,
        "drum_min": float(ok["drum_aor"].min()),
        "drum_max": float(ok["drum_aor"].max()),
        "target_band": [lo, hi],
        "n_inband_drum": n_inband,
        "target_reachable": reachable,
        "noise_floor_deg": noise_floor,
        "go": go,
        "criterion": "span >= 3 deg AND |spearman| >= 0.8 AND band reachable",
    }


def make_plot(df: pd.DataFrame, out_path: Path = PLOT) -> Path:
    """Two-panel figure: the degeneracy (static AoR flat along the valley)
    vs the break (drum angle trending across it)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    df = df.sort_values("fric")
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5), sharex=True)

    ax1.axhspan(TARGET_AOR - SIGMA_AOR, TARGET_AOR + SIGMA_AOR,
                color="tab:blue", alpha=0.12, label="static target ±σ")
    ax1.errorbar(df["fric"], df["aor"], yerr=df["aor_std"], fmt="o-",
                 c="tab:blue", capsize=3)
    ax1.set_xlabel("sliding friction μ_s")
    ax1.set_ylabel("static AoR  [deg]")
    ax1.set_title("the valley: static AoR is flat along it")
    ax1.legend(fontsize=8)

    ax2.axhspan(TARGET_DRUM - SIGMA_DRUM, TARGET_DRUM + SIGMA_DRUM,
                color="tab:green", alpha=0.15,
                label=f"drum target {TARGET_DRUM} ± {SIGMA_DRUM}°")
    ax2.errorbar(df["fric"], df["drum_aor"], yerr=df["drum_aor_std"], fmt="o-",
                 c="tab:red", capsize=3)
    for _, r in df.iterrows():
        ax2.annotate(f"μr {r['rollfric']:.2f}", (r["fric"], r["drum_aor"]),
                     textcoords="offset points", xytext=(4, -10), fontsize=7)
    ax2.set_xlabel("sliding friction μ_s")
    ax2.set_ylabel("drum dynamic AoR  [deg]")
    ax2.set_title("the break: drum angle along the same valley")
    ax2.legend(fontsize=8)

    fig.suptitle("Phase 9 valley check — does the drum discriminate?")
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=140)
    plt.close(fig)
    return out_path


def make_sheet(df: pd.DataFrame, out_path: Path = SHEET) -> Path:
    items = []
    for _, r in df.sort_values("fric").iterrows():
        label = (f"μs {r['fric']:.2f} μr {r['rollfric']:.2f}  "
                 f"drum {r['drum_aor']:.1f}°" if pd.notna(r["drum_aor"])
                 else f"μs {r['fric']:.2f}  FAILED")
        items.append((label, Path(r["drum_trial"]) / "snapshot.png"))
    return render.contact_sheet(items, out_path, ncols=3)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    rn = sub.add_parser("run", help="evaluate the 9 anchors and report")
    rn.add_argument("--seeds", type=int, default=2)
    rn.add_argument("--jobs", type=int)
    rn.add_argument("--noise-floor", type=float,
                    help="drum seed-noise floor [deg] from the M2 study")
    sub.add_parser("report", help="re-plot + verdict from the existing CSV")
    args = ap.parse_args()

    OUTDIR.mkdir(parents=True, exist_ok=True)
    if args.cmd == "run":
        df = run_check(n_seeds=args.seeds, jobs=args.jobs)
        df.to_csv(CSV, index=False)
        nf = args.noise_floor
    else:
        df = pd.read_csv(CSV)
        nf = None

    v = verdict(df, noise_floor=nf)
    VERDICT.write_text(json.dumps(v, indent=2))
    make_plot(df)
    try:
        make_sheet(df)
    except Exception as err:  # noqa: BLE001 — the sheet is a nicety
        print(f"WARNING: contact sheet failed: {err}", file=sys.stderr)
    print(df.to_string(index=False))
    print(json.dumps(v, indent=2))
    print("VERDICT:", "GO — the drum discriminates" if v["go"]
          else "NO-GO — see ROADMAP Phase-9 risk path")


if __name__ == "__main__":
    main()
