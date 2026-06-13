"""Phase-10 hold-out validation — 45-deg inclined drum vs Sugirbay 2022.

Phases 8-9 calibrated against the static heap and the VERTICAL drum; the
deliverable is an equivalence family (fric 0.25-0.60, rollfric
anti-correlated) with a representative member verified at 5 seeds. This
script predicts a measurement NEVER used in calibration — the acrylic drum
inclined 45 deg (target 43.65 +/- 2.92 deg, Table 1/2 of the paper; see
experiments/ground-truth-wheat-literature.md) — and asks: do the calibrated
particle-particle parameters describe the MATERIAL, not the calibration
tests? All wall friction in the drum45 response is pinned to the published
wheat-acrylic pair, so only the calibrated set is under test.

Pre-registration: `prestate` writes acceptance.json (target, sigma, the
acceptance multiple, anchors, deviations) and `run` REFUSES to start
without it — the criterion is stated before any compute, enforced by code.

Anchors: the representative family member at 5 seeds (primary, gating) plus
the two family endpoints at 2 seeds (informational: does 45 deg
discriminate along the valley? Pre-stated expectation: probably not — with
all walls acrylic the response is plausibly family-degenerate like the
vertical drum, in which case the validation validates the family, which is
the honest Phase-9 deliverable).

CLI:
    .venv/bin/python calibration/validate.py prestate [--force]
    .venv/bin/python calibration/validate.py run [--jobs N]
    .venv/bin/python calibration/validate.py report   # re-verdict from CSV
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from calibration import render, runner  # noqa: E402

OUTDIR = REPO_ROOT / "results" / "phase10-validation"
ACCEPTANCE = OUTDIR / "acceptance.json"
CSV = OUTDIR / "validation.csv"
PLOT = OUTDIR / "validation.png"
SHEET = OUTDIR / "validation_contact_sheet.png"
VERDICT = OUTDIR / "validation_verdict.json"

# Hold-out target: acrylic drum, alpha = 45 deg (Sugirbay 2022 Table 1 row
# mean; sigma = pooled within-group sqrt(MS_within) from their Table 2 ANOVA
# — the same convention as the vertical target's sqrt(9.73) = 3.1).
TARGET_45, SIGMA_45 = 43.65, 2.92
ACCEPT_MULTIPLE = 2.0

# The Phase-9 deliverable, verbatim (valley_check.py / family_verification):
# mid-valley representative + the two family endpoints. canonical()
# re-rounds to 4 dp, so these line up with the existing records exactly.
REPRESENTATIVE = {"fric": 0.4001, "rollfric": 0.1374, "rest": 0.5762}
ENDPOINTS = [
    {"fric": 0.2477, "rollfric": 0.2249, "rest": 0.4945},   # low-fric end
    {"fric": 0.6000, "rollfric": 0.1203, "rest": 0.7000},   # high-fric end
]
N_SEEDS_REP, N_SEEDS_END = 5, 2


def prestate(*, force: bool = False) -> dict:
    """Write the pre-registered acceptance criterion BEFORE any compute.

    Refuses to overwrite an existing pre-registration unless --force — a
    silently rewritten criterion is no pre-registration at all.
    """
    if ACCEPTANCE.exists() and not force:
        raise SystemExit(
            f"{ACCEPTANCE} already exists — the criterion is pre-registered; "
            "use --force only to deliberately restate it")
    acc = {
        "scenario": "drum45 hold-out: acrylic drum inclined 45 deg, 5 rpm, "
                    "50% fill (Sugirbay et al. 2022, never used in calibration)",
        "target_deg": TARGET_45,
        "sigma_deg": SIGMA_45,
        "sigma_source": "pooled within-group sqrt(MS_within) = sqrt(8.52), "
                        "Table 2 ANOVA at alpha=45 (16 df) — same convention "
                        "as the vertical drum target",
        "multiple": ACCEPT_MULTIPLE,
        "criterion": f"|predicted - {TARGET_45}| <= "
                     f"{ACCEPT_MULTIPLE}*sigma_45 = "
                     f"{ACCEPT_MULTIPLE * SIGMA_45:.2f} deg on the "
                     f"representative set, with n_ok >= {N_SEEDS_REP - 1} of "
                     f"{N_SEEDS_REP} seeds and no steadiness-drift warnings",
        "anchors": {
            "representative": {**REPRESENTATIVE, "n_seeds": N_SEEDS_REP,
                               "role": "gating"},
            "endpoints": [{**e, "n_seeds": N_SEEDS_END,
                           "role": "informational-discrimination"}
                          for e in ENDPOINTS],
        },
        "fixed_protocol_inputs": {
            "wall_friction": "all walls (shell + covers) wheat-acrylic "
                             "0.36/0.29 — Sugirbay Table 11, calibrated on "
                             "their 7-sphere clumps, carried as fixed input",
            "rotation": "5 rpm (ROTPER 12 s)",
            "fill": "50% (NPART 4600)",
        },
        "prestated_deviations": [
            "axial length 25 mm vs published 50 mm — biases the 45-deg "
            "comparison MORE than vertical (bed rests on the cover, trace "
            "measured at the cover); bounded by a one-off 50 mm sensitivity "
            "run in M3",
            "single spheres vs 7-sphere clumps — mu_r absorbs shape effects "
            "(locked Phase-3 decision)",
            "2-5 seeds vs 5 physical reps x 4 frames",
        ],
        "prestated_expectation_endpoints":
            "with all walls pinned to acrylic the 45-deg response is "
            "plausibly family-degenerate (like the vertical drum); endpoint "
            "separation is informational, not gating",
        "prestated_date": str(date.today()),
    }
    OUTDIR.mkdir(parents=True, exist_ok=True)
    ACCEPTANCE.write_text(json.dumps(acc, indent=2))
    return acc


def run_validation(*, jobs: int | None = None) -> pd.DataFrame:
    """Evaluate the representative (5 seeds) + endpoints (2 seeds) on the
    drum45 response; one tidy row per anchor."""
    anchors = ([{**REPRESENTATIVE, "_role": "representative",
                 "_n_seeds": N_SEEDS_REP}]
               + [{**e, "_role": "endpoint", "_n_seeds": N_SEEDS_END}
                  for e in ENDPOINTS])
    rows = []
    for a in anchors:
        params = {k: v for k, v in a.items() if not k.startswith("_")}
        res = runner.evaluate(params, n_seeds=a["_n_seeds"], jobs=jobs,
                              response="drum45")
        rows.append({
            **params,
            "role": a["_role"],
            "n_seeds": a["_n_seeds"],
            "drum45_aor": res["drum_aor"],
            "drum45_aor_std": res["drum_aor_std"],
            "drum45_frame_std": res["drum_frame_std"],
            "n_ok": res["n_ok"],
            "n_drift_warnings": sum("drift" in w for w in res["warnings"]),
            "trial": res["trial_dirs"][0],
        })
    return pd.DataFrame(rows)


def verdict(df: pd.DataFrame, acceptance: dict) -> dict:
    """Score the run against the PRE-STATED criterion. Gating: the
    representative anchor. Informational: endpoint discrimination."""
    target = acceptance["target_deg"]
    tol = acceptance["multiple"] * acceptance["sigma_deg"]

    rep = df[df["role"] == "representative"].iloc[0]
    rep_err = (abs(rep["drum45_aor"] - target)
               if pd.notna(rep["drum45_aor"]) else None)
    rep_pass = bool(
        rep_err is not None
        and rep_err <= tol
        and rep["n_ok"] >= rep["n_seeds"] - 1
        and rep["n_drift_warnings"] == 0
    )

    ends = df[df["role"] == "endpoint"].dropna(subset=["drum45_aor"])
    ok = df.dropna(subset=["drum45_aor"])
    span = (float(ok["drum45_aor"].max() - ok["drum45_aor"].min())
            if len(ok) > 1 else None)
    seed_noise = (float(ok["drum45_aor_std"].mean()) if len(ok) else None)
    discriminates = (bool(span is not None and seed_noise is not None
                          and span > 3.0 * max(seed_noise, 0.1))
                     if len(ends) == 2 else None)

    per_anchor = [
        {"fric": r["fric"], "rollfric": r["rollfric"], "role": r["role"],
         "predicted_deg": (float(r["drum45_aor"])
                           if pd.notna(r["drum45_aor"]) else None),
         "seed_std": float(r["drum45_aor_std"]),
         "n_ok": int(r["n_ok"]),
         "in_band": (bool(abs(r["drum45_aor"] - target) <= tol)
                     if pd.notna(r["drum45_aor"]) else False)}
        for _, r in df.iterrows()
    ]
    return {
        "scenario": acceptance["scenario"],
        "target_deg": target,
        "sigma_deg": acceptance["sigma_deg"],
        "tolerance_deg": tol,
        "criterion": acceptance["criterion"],
        "representative": {
            "params": {k: float(rep[k]) for k in ("fric", "rollfric", "rest")},
            "predicted_deg": (float(rep["drum45_aor"])
                              if pd.notna(rep["drum45_aor"]) else None),
            "seed_std": float(rep["drum45_aor_std"]),
            "abs_error_deg": rep_err,
            "n_ok": int(rep["n_ok"]),
            "n_drift_warnings": int(rep["n_drift_warnings"]),
        },
        "passed": rep_pass,
        "family_span_deg": span,
        "mean_seed_std_deg": seed_noise,
        "endpoints_discriminate": discriminates,
        "per_anchor": per_anchor,
    }


def make_plot(df: pd.DataFrame, acceptance: dict, out_path: Path = PLOT) -> Path:
    """Measured band vs predicted points along the family fric axis."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    target = acceptance["target_deg"]
    sig = acceptance["sigma_deg"]
    mult = acceptance["multiple"]

    df = df.sort_values("fric")
    fig, ax = plt.subplots(figsize=(8, 5.5))
    ax.axhspan(target - mult * sig, target + mult * sig, color="tab:green",
               alpha=0.10, label=f"acceptance ±{mult:.0f}σ ({mult * sig:.2f}°)")
    ax.axhspan(target - sig, target + sig, color="tab:green", alpha=0.18,
               label=f"measured {target} ± {sig}°")
    ax.axhline(target, c="tab:green", lw=1.0)
    for role, c, ms in (("endpoint", "tab:blue", 7),
                        ("representative", "tab:red", 10)):
        sel = df[df["role"] == role]
        ax.errorbar(sel["fric"], sel["drum45_aor"], yerr=sel["drum45_aor_std"],
                    fmt="o", ms=ms, c=c, capsize=4,
                    label=f"{role} (predicted)")
    for _, r in df.iterrows():
        ax.annotate(f"μr {r['rollfric']:.2f}", (r["fric"], r["drum45_aor"]),
                    textcoords="offset points", xytext=(6, -12), fontsize=8)
    ax.set_xlabel("sliding friction μ_s  (family axis)")
    ax.set_ylabel("45° drum dynamic AoR  [deg]")
    ax.set_title("Phase 10 hold-out: predicted vs measured (never calibrated)")
    ax.legend(fontsize=8, loc="best")
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=140)
    plt.close(fig)
    return out_path


def make_sheet(df: pd.DataFrame, out_path: Path = SHEET) -> Path:
    items = []
    for _, r in df.sort_values("fric").iterrows():
        label = (f"μs {r['fric']:.2f} μr {r['rollfric']:.2f}  "
                 f"45° {r['drum45_aor']:.1f}°" if pd.notna(r["drum45_aor"])
                 else f"μs {r['fric']:.2f}  FAILED")
        items.append((label, Path(r["trial"]) / "snapshot.png"))
    return render.contact_sheet(items, out_path, ncols=3)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    ps = sub.add_parser("prestate", help="pre-register the acceptance criterion")
    ps.add_argument("--force", action="store_true",
                    help="deliberately restate an existing pre-registration")
    rn = sub.add_parser("run", help="run the hold-out anchors and verdict")
    rn.add_argument("--jobs", type=int)
    sub.add_parser("report", help="re-verdict + re-plot from the existing CSV")
    args = ap.parse_args()

    OUTDIR.mkdir(parents=True, exist_ok=True)
    if args.cmd == "prestate":
        acc = prestate(force=args.force)
        print(json.dumps(acc, indent=2))
        return

    if not ACCEPTANCE.exists():
        raise SystemExit(
            "no acceptance.json — run `validate.py prestate` BEFORE any "
            "compute; the criterion must be pre-registered")
    acceptance = json.loads(ACCEPTANCE.read_text())

    if args.cmd == "run":
        df = run_validation(jobs=args.jobs)
        df.to_csv(CSV, index=False)
    else:
        df = pd.read_csv(CSV)

    v = verdict(df, acceptance)
    VERDICT.write_text(json.dumps(v, indent=2))
    make_plot(df, acceptance, out_path=PLOT)
    try:
        make_sheet(df, out_path=SHEET)
    except Exception as err:  # noqa: BLE001 — the sheet is a nicety
        print(f"WARNING: contact sheet failed: {err}", file=sys.stderr)
    print(df.to_string(index=False))
    print(json.dumps(v, indent=2))
    print("VERDICT:", "PASS — hold-out within the pre-stated tolerance"
          if v["passed"] else "FAIL — see ROADMAP Phase-10 risk path")


if __name__ == "__main__":
    main()
