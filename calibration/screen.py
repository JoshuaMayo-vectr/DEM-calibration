"""Latin-hypercube screen & sensitivity analysis for DEM calibration (Phase 7).

Maps the angle-of-repose response surface before any optimizer compute is spent.
Draws a Latin-hypercube design over the literature-informed calibration ranges,
runs each candidate through the Phase-6 driver (cached, resumable, 2-seed
averaged), then (a) confirms the measured target lies inside the reachable AoR
range and (b) ranks which parameters actually move the angle so the insensitive
ones can be frozen before Phase 8. The output gates Checkpoint 3 and doubles as
the free training set the Phase-8 surrogate is seeded from.

Sweeps three parameters — particle-particle sliding friction, rolling friction
(epsd2) and restitution — with particle-wall friction mirrored (the runner
default). Sensitivity uses SALib's given-data delta analyzer (delta
moment-independent index + first-order Sobol S1, both valid on an LHS design,
unlike Sobol's Saltelli-only estimator), cross-checked with Spearman rank
correlation. No new simulation code: this orchestrates calibration.runner and
reuses calibration.render.contact_sheet for the per-candidate skim.

CLI:
    .venv/bin/python calibration/screen.py sample  [--n 60] [--seed N]
    .venv/bin/python calibration/screen.py run      [--n 60] [--seeds 2] [--jobs N]
    .venv/bin/python calibration/screen.py analyze
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

# ------------------------------------------------------------- constants
OUTDIR = REPO_ROOT / "results" / "phase7-lhs"
SAMPLE_CSV = OUTDIR / "lhs_sample.csv"
RESULTS_CSV = OUTDIR / "lhs_results.csv"
SENS_JSON = OUTDIR / "sensitivity.json"
SENS_PNG = OUTDIR / "sensitivity.png"
SCATTER_PNG = OUTDIR / "response_scatter.png"
SHEET_PNG = OUTDIR / "contact_sheet.png"

# The screen sweeps the three calibration knobs over the wheat literature ranges
# (experiments/ground-truth-wheat-literature.md), with rollfric widened past the
# literature 0.0-0.15 ceiling to 0.25 so Checkpoint 3 can confirm the target is
# bracketed *interior* rather than clipped at the edge. All inside runner.RANGES.
SCREEN_PROBLEM = {
    "num_vars": 3,
    "names": ["fric", "rollfric", "rest"],
    "bounds": [[0.20, 0.60], [0.00, 0.25], [0.30, 0.70]],
}
TARGET_AOR = 27.0       # deg — wheat lifted-cylinder literature target
TARGET_SIGMA = 1.5      # deg — assumed spread / calibration tolerance
LHS_SEED = 12345        # fixed -> reproducible design
N_DEFAULT = 60

# delta needs a reasonable point count for its kNN estimate; below this we still
# report Spearman but leave the SALib indices NaN (e.g. on the smoke run).
MIN_SALIB_SAMPLES = 16
# Freeze rule. The delta moment-independent estimator has a non-zero noise floor
# (~0.06 at n=60) even for an irrelevant parameter, so an absolute delta cut is
# unreliable; first-order Sobol S1 discriminates cleanly. A parameter is frozen
# when its S1 is negligible AND its Spearman rho is not statistically significant
# (|rho| < 0.25 ≈ the p>0.05 floor at n≈60). rest is the expected freeze.
FREEZE_S1 = 0.05
FREEZE_RHO = 0.25


# ------------------------------------------------------------- sampling
def sample(n: int = N_DEFAULT, seed: int = LHS_SEED) -> np.ndarray:
    """Latin-hypercube design of shape (n, 3) over SCREEN_PROBLEM. Deterministic."""
    from SALib.sample import latin
    return latin.sample(SCREEN_PROBLEM, n, seed=seed)


def rows_to_params(X: np.ndarray) -> list[dict]:
    """Map LHS rows to runner param dicts. Walls mirror inside runner.canonical."""
    names = SCREEN_PROBLEM["names"]
    return [{names[j]: float(row[j]) for j in range(len(names))} for row in X]


# ------------------------------------------------------------- run + collect
def run_screen(X: np.ndarray, *, n_seeds: int = 2, jobs: int | None = None) -> list[dict]:
    """Evaluate every LHS candidate through the cached Phase-6 driver. Resumable:
    a killed batch reruns only the candidates without a cached success."""
    return runner.evaluate_batch(rows_to_params(X), n_seeds=n_seeds, jobs=jobs)


def collect(X: np.ndarray, results: list[dict]) -> pd.DataFrame:
    """Tidy one-row-per-candidate frame. Parameter columns hold the canonical
    (actually-simulated) values from the driver; aor is NaN for an all-seeds
    failure (rare here — no gravz fault is injected)."""
    names = SCREEN_PROBLEM["names"]
    rows = []
    for row, res in zip(X, results):
        p = res.get("params") or {}
        out = {n: float(p.get(n, row[j])) for j, n in enumerate(names)}
        aor = res.get("aor")
        out["aor"] = float(aor) if aor is not None else np.nan
        out["aor_std"] = res.get("aor_std")
        bd = res.get("bulk_density")
        out["bulk_density"] = float(bd) if bd is not None else np.nan
        out["n_ok"] = int(res.get("n_ok", 0))
        out["hash"] = runner.params_hash(p) if p else ""
        dirs = res.get("trial_dirs") or []
        out["trial_dir"] = dirs[0] if dirs else ""
        rows.append(out)
    return pd.DataFrame(rows)


# ------------------------------------------------------------- analysis
def analyze_sensitivity(df: pd.DataFrame, *, seed: int = LHS_SEED) -> dict:
    """Delta moment-independent + first-order Sobol indices (SALib, given-data)
    plus Spearman rho per parameter. Candidates with no AoR are dropped and
    counted. Below MIN_SALIB_SAMPLES the SALib indices are left NaN."""
    from scipy.stats import spearmanr

    names = SCREEN_PROBLEM["names"]
    ok = df.dropna(subset=["aor"])
    n_dropped = len(df) - len(ok)
    X = ok[names].to_numpy(dtype=float)
    Y = ok["aor"].to_numpy(dtype=float)

    nan = {n: float("nan") for n in names}
    d, dconf, s1, s1conf = dict(nan), dict(nan), dict(nan), dict(nan)
    have_salib = len(ok) >= MIN_SALIB_SAMPLES
    if have_salib:
        from SALib.analyze import delta
        sal = delta.analyze(SCREEN_PROBLEM, X, Y, seed=seed, print_to_console=False)
        for j, n in enumerate(names):
            d[n] = float(sal["delta"][j])
            dconf[n] = float(sal["delta_conf"][j])
            s1[n] = float(sal["S1"][j])
            s1conf[n] = float(sal["S1_conf"][j])

    rho = {}
    for j, n in enumerate(names):
        r = spearmanr(X[:, j], Y).statistic if len(ok) > 2 else float("nan")
        rho[n] = float(r)

    sens = {
        "names": names,
        "delta": d, "delta_conf": dconf, "S1": s1, "S1_conf": s1conf,
        "spearman": rho,
        "n_used": int(len(ok)),
        "n_dropped": int(n_dropped),
        "salib_ok": have_salib,
    }
    # Rank by delta when available, else by |rho| (smoke run).
    keyfn = (lambda n: d[n]) if have_salib else (lambda n: abs(rho[n]))
    sens["ranking"] = sorted(names, key=lambda n: (np.nan_to_num(keyfn(n))), reverse=True)
    # Freezing is a real decision: only make it with the full SALib indices.
    sens["frozen"] = [] if not have_salib else [
        n for n in names
        if (s1[n] < FREEZE_S1) and (abs(np.nan_to_num(rho[n])) < FREEZE_RHO)
    ]
    return sens


def bracketing(df: pd.DataFrame) -> dict:
    """Is the target AoR band reachable within the screened response range?"""
    aor = df["aor"].dropna()
    lo, hi = TARGET_AOR - TARGET_SIGMA, TARGET_AOR + TARGET_SIGMA
    amin = float(aor.min()) if len(aor) else float("nan")
    amax = float(aor.max()) if len(aor) else float("nan")
    nearest = None
    if len(aor):
        idx = (df["aor"] - TARGET_AOR).abs().idxmin()
        r = df.loc[idx]
        nearest = {n: float(r[n]) for n in SCREEN_PROBLEM["names"]}
        nearest["aor"] = float(r["aor"])
    return {
        "target": TARGET_AOR, "sigma": TARGET_SIGMA,
        "aor_min": amin, "aor_max": amax,
        "target_bracketed": bool(len(aor) and amin <= lo and amax >= hi),
        "nearest": nearest,
        "n_used": int(len(aor)),
    }


# ------------------------------------------------------------- plots
def plot_sensitivity(sens: dict, out_path: str | Path) -> Path:
    """Horizontal bar chart of delta and S1 per parameter, with bootstrap-confidence
    error bars; Spearman rho annotated on the tick labels."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    names = sens["names"]
    y = np.arange(len(names))
    h = 0.38
    delta = [sens["delta"][n] for n in names]
    s1 = [sens["S1"][n] for n in names]
    dconf = np.nan_to_num([sens["delta_conf"][n] for n in names])
    s1conf = np.nan_to_num([sens["S1_conf"][n] for n in names])

    fig, ax = plt.subplots(figsize=(7, 4))
    ax.barh(y + h / 2, delta, height=h, xerr=dconf, capsize=3,
            color="tab:blue", label="δ (moment-independent)")
    ax.barh(y - h / 2, s1, height=h, xerr=s1conf, capsize=3,
            color="tab:orange", label="S1 (first-order Sobol)")
    ax.set_yticks(y)
    ax.set_yticklabels([f"{n}\nρ={sens['spearman'][n]:+.2f}" for n in names])
    ax.set_xlabel("sensitivity index")
    ax.set_title(f"Phase-7 LHS sensitivity (n={sens['n_used']} candidates)")
    ax.legend(loc="lower right", fontsize=8)
    ax.grid(True, axis="x", lw=0.4, alpha=0.6)
    fig.tight_layout()
    fig.savefig(out_path, dpi=140)
    plt.close(fig)
    return Path(out_path)


def plot_response_scatter(df: pd.DataFrame, out_path: str | Path) -> Path:
    """1x3 panel: AoR vs each swept parameter, points colored by rolling friction,
    with the target band shaded — shows the friction valley and the bracketing."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    names = SCREEN_PROBLEM["names"]
    ok = df.dropna(subset=["aor"])
    lo, hi = TARGET_AOR - TARGET_SIGMA, TARGET_AOR + TARGET_SIGMA

    fig, axes = plt.subplots(1, 3, figsize=(13, 4), sharey=True)
    sc = None
    for ax, name in zip(axes, names):
        sc = ax.scatter(ok[name], ok["aor"], c=ok["rollfric"], cmap="viridis",
                        s=28, alpha=0.85, edgecolor="0.3", linewidth=0.3)
        ax.axhspan(lo, hi, color="tab:green", alpha=0.15,
                   label=f"target {TARGET_AOR:g}±{TARGET_SIGMA:g}°")
        ax.axhline(TARGET_AOR, color="tab:green", lw=1.0, ls="--")
        ax.set_xlabel(name)
        ax.grid(True, lw=0.4, alpha=0.5)
    axes[0].set_ylabel("angle of repose [deg]")
    axes[0].legend(loc="upper left", fontsize=8)
    if sc is not None:
        cb = fig.colorbar(sc, ax=axes, fraction=0.025, pad=0.02)
        cb.set_label("rollfric")
    fig.suptitle(f"Phase-7 LHS response (n={len(ok)} candidates)")
    fig.savefig(out_path, dpi=140)
    plt.close(fig)
    return Path(out_path)


def build_contact_sheet(df: pd.DataFrame, out_path: str | Path,
                        ncols: int | None = None) -> Path:
    """Tile every candidate's first-seed snapshot for a minute-scale skim. Reuses
    render.contact_sheet, which renders a grey MISSING tile for any absent image."""
    items = []
    for _, r in df.iterrows():
        td = str(r.get("trial_dir") or "")
        snap = Path(td) / "snapshot.png" if td else Path("__missing__")
        aor = r["aor"]
        atxt = f"{aor:.1f}°" if pd.notna(aor) else "n/a"
        items.append((f"f{r['fric']:.2f} r{r['rollfric']:.2f}  {atxt}", snap))
    return render.contact_sheet(items, out_path, ncols=ncols)


# ------------------------------------------------------------- summary
def summarize(df: pd.DataFrame, sens: dict, brk: dict) -> str:
    lines = []
    lines.append(f"candidates: {len(df)} | measured: {sens['n_used']} | "
                 f"dropped (no AoR): {sens['n_dropped']}")
    lines.append(f"AoR range: {brk['aor_min']:.1f}–{brk['aor_max']:.1f}°  "
                 f"target {brk['target']:g}±{brk['sigma']:g}°  "
                 f"-> bracketed: {'YES' if brk['target_bracketed'] else 'NO'}")
    if brk["nearest"]:
        nz = brk["nearest"]
        lines.append(f"nearest to target: AoR {nz['aor']:.1f}° at "
                     f"fric={nz['fric']:.3f} rollfric={nz['rollfric']:.3f} rest={nz['rest']:.3f}")
    lines.append("sensitivity (delta | S1 | Spearman ρ):")
    for n in sens["ranking"]:
        lines.append(f"  {n:9s} δ={sens['delta'][n]:.3f}  S1={sens['S1'][n]:.3f}  "
                     f"ρ={sens['spearman'][n]:+.3f}")
    lines.append(f"freeze candidates: {sens['frozen'] or '(none)'} | "
                 f"active params: {[n for n in sens['names'] if n not in sens['frozen']]}")
    return "\n".join(lines)


# ------------------------------------------------------------- entry point
def _load_or_make_sample(n: int, seed: int) -> pd.DataFrame:
    """Read the persisted design if present (so resume keeps an identical sample),
    else generate and persist it."""
    names = SCREEN_PROBLEM["names"]
    if SAMPLE_CSV.exists():
        return pd.read_csv(SAMPLE_CSV)
    X = sample(n, seed)
    df = pd.DataFrame(X, columns=names)
    OUTDIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(SAMPLE_CSV, index=False)
    return df


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("sample", help="write the LHS design to lhs_sample.csv")
    sp.add_argument("--n", type=int, default=N_DEFAULT)
    sp.add_argument("--seed", type=int, default=LHS_SEED)

    rn = sub.add_parser("run", help="run the screen through the driver (resumable)")
    rn.add_argument("--n", type=int, default=N_DEFAULT)
    rn.add_argument("--seed", type=int, default=LHS_SEED)
    rn.add_argument("--seeds", type=int, default=2, help="RNG seeds averaged per candidate")
    rn.add_argument("--jobs", type=int, help="concurrent sims (default: auto)")

    sub.add_parser("analyze", help="plots + sensitivity + bracketing from lhs_results.csv")

    args = ap.parse_args()
    names = SCREEN_PROBLEM["names"]

    if args.cmd == "sample":
        X = sample(args.n, args.seed)
        OUTDIR.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(X, columns=names).to_csv(SAMPLE_CSV, index=False)
        print(f"wrote {len(X)} LHS candidates -> {SAMPLE_CSV}")

    elif args.cmd == "run":
        sdf = _load_or_make_sample(args.n, args.seed)
        X = sdf[names].to_numpy(dtype=float)
        print(f"running {len(X)} candidates × {args.seeds} seeds through the driver...")
        results = run_screen(X, n_seeds=args.seeds, jobs=args.jobs)
        df = collect(X, results)
        OUTDIR.mkdir(parents=True, exist_ok=True)
        df.to_csv(RESULTS_CSV, index=False)
        n_ok = int(df["aor"].notna().sum())
        print(f"wrote {len(df)} results ({n_ok} with AoR) -> {RESULTS_CSV}")

    elif args.cmd == "analyze":
        if not RESULTS_CSV.exists():
            ap.error(f"{RESULTS_CSV} not found — run `screen.py run` first")
        df = pd.read_csv(RESULTS_CSV)
        sens = analyze_sensitivity(df)
        brk = bracketing(df)
        plot_sensitivity(sens, SENS_PNG)
        plot_response_scatter(df, SCATTER_PNG)
        build_contact_sheet(df, SHEET_PNG)
        SENS_JSON.write_text(json.dumps({"sensitivity": sens, "bracketing": brk}, indent=2))
        print(summarize(df, sens, brk))
        print(f"\nwrote {SENS_PNG.name}, {SCATTER_PNG.name}, {SHEET_PNG.name}, {SENS_JSON.name}")


if __name__ == "__main__":
    main()
