"""Phase-10 material card — the pipeline's deliverable.

Assembles materials/wheat.json from the calibration and validation
artifacts already on disk, validates it against materials/schema.json, and
replays it: `reproduce` runs a fresh runner.evaluate using ONLY the card's
contents and asserts the calibrated responses come back within the card's
stated tolerances (the ROADMAP Phase-10 exit criterion, verbatim — on this
machine a cache-hit replay in minutes; on a fresh build the tolerance
absorbs platform/MPI nondeterminism).

The card's point values are the Phase-9 REPRESENTATIVE family member
(fric 0.4001 / rollfric 0.1374 / rest 0.5762, verified at 5 seeds), from
family_verification.json; the family itself is the stated uncertainty on
(fric, rollfric). NOTE: results/phase9-drum/best.json is NOT evidence —
the Phase-9 multi-response optimizer study was cancelled at the M4 gate,
and that file's former content (fric 0.617) was a test artifact written
by a def-time default-arg bug in optimize.write_best (fixed + file
tombstoned 2026-06-13, Phase 8.5).

CLI:
    .venv/bin/python calibration/material_card.py build
    .venv/bin/python calibration/material_card.py validate-card [--card PATH]
    .venv/bin/python calibration/material_card.py reproduce [--card PATH]
        [--seeds N] [--jobs N]
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

SCHEMA = REPO_ROOT / "materials" / "schema.json"
CARD = REPO_ROOT / "materials" / "wheat.json"

# artifact sources (everything the builder reads — no new analysis here)
FAMILY_VERIFICATION = REPO_ROOT / "results" / "phase9-drum" / "family_verification.json"
VALLEY_CSV = REPO_ROOT / "results" / "phase9-drum" / "valley_check.csv"
ACCEPTANCE = REPO_ROOT / "results" / "phase10-validation" / "acceptance.json"
VERDICT = REPO_ROOT / "results" / "phase10-validation" / "validation_verdict.json"
GROUND_TRUTH = "experiments/ground-truth-wheat-literature.md"


def build() -> dict:
    """Assemble the card purely from existing artifacts; schema-validate;
    write materials/wheat.json."""
    import pandas as pd

    fv = json.loads(FAMILY_VERIFICATION.read_text())
    verdict = json.loads(VERDICT.read_text())
    acceptance = json.loads(ACCEPTANCE.read_text())
    valley = pd.read_csv(VALLEY_CSV)

    rep = fv["params"]["aor"]   # canonical representative member
    anchors = [
        {"fric": float(r["fric"]), "rollfric": float(r["rollfric"]),
         "aor_deg": round(float(r["aor"]), 2),
         "drum_aor_deg": round(float(r["drum_aor"]), 2)}
        for _, r in valley.iterrows()
    ]

    card = {
        "name": "wheat-dry-single-sphere",
        "material": "wheat grain, dry, cohesionless (literature ground "
                    "truth; source experiments used AK58 at ~14% moisture)",
        # 1.0.1 (2026-06-13): evidence citation corrected — the optimizer_best
        # pointer described a test artifact (see the best.json tombstone);
        # parameters, responses and validation are unchanged from 1.0.0
        "version": "1.0.1",
        "date": str(date.today()),
        "engine": {
            "code": "LIGGGHTS-PUBLIC",
            "version": "3.8.0",
            "build": "lmp_auto from source, arm64 macOS, Open MPI, Boost, "
                     "USE_VTK=OFF (see ROADMAP Phase 0); responses verified "
                     "on this build — re-verify a few seeds after any rebuild",
        },
        "contact_model": {
            "pair_style": "gran model hertz tangential history "
                          "rolling_friction epsd2",
            "cohesion": "none (dry wheat is cohesionless at storage moisture)",
            "particle_shape": "sphere (mu_r absorbs grain-shape effects — "
                              "the locked Phase-3 modelling decision)",
        },
        "parameters": {
            "fric": {
                "value": rep["fric"], "role": "calibrated",
                "description": "particle-particle sliding friction; one "
                               "member of the equivalence family — see "
                               "equivalence_family for the stated uncertainty",
            },
            "rollfric": {
                "value": rep["rollfric"], "role": "calibrated",
                "description": "particle-particle rolling friction (epsd2); "
                               "anti-correlated with fric along the family",
            },
            "rest": {
                "value": rep["rest"], "role": "calibrated-weak",
                "description": "restitution — negligible influence on the "
                               "calibrated quasi-static/rolling responses "
                               "(Phase-7 sensitivity: delta 0.02); "
                               "effectively free within 0.3-0.7",
            },
        },
        "equivalence_family": {
            "constraint": "fric 0.25-0.60 anti-correlated with rollfric "
                          "0.22-0.12 (rest free): every anchor matches BOTH "
                          "calibrated responses within spread — a single "
                          "parameter point is NOT identified by the "
                          "calibrated responses",
            "anchors": anchors,
            "caveat": "the family is breakable only by a measured orifice "
                      "flow rate (drawdown discriminates 8x seed noise along "
                      "the family — Phase-9 probe — but no literature target "
                      "is tight enough; a physical measurement at +/-2 g/s "
                      "would localize a unique point)",
        },
        "fixed_inputs": {
            "particle_density_kgm3": 1400,
            "psd_mm": {"diameters": [3.4, 3.7, 4.0],
                       "mass_weights": [0.25, 0.50, 0.25]},
            "youngs_modulus_pa": 1.0e7,
            "youngs_modulus_note": "softened 2-3 orders below reality for "
                                   "timestep (standard DEM practice; AoR "
                                   "verified insensitive 1e7-5e7); pair with "
                                   "timestep_s",
            "poisson_ratio": 0.25,
            "timestep_s": 8.0e-6,
            "wall_acrylic": {
                "fric": 0.36, "rollfric": 0.29,
                "source": "Sugirbay et al. 2022 Table 11 (wheat-acrylic, "
                          "calibrated on their 7-sphere clumps — carried as "
                          "a fixed protocol input)",
            },
        },
        "responses": {
            "aor": {
                "value_deg": round(fv["aor"], 2),
                "std_deg": round(fv["aor_std"], 2),
                "n_seeds": fv["n_seeds"],
                "target_deg": 27.0,
                "target_sigma_deg": 1.5,
                "protocol": "static AoR, lifted cylinder R 0.040 m / "
                            "H 0.100 m, 4000 spheres, lift 10 mm/s "
                            "(method-bound; templates/aor.in)",
            },
            "drum": {
                "value_deg": round(fv["drum_aor"], 2),
                "std_deg": round(fv["drum_aor_std"], 2),
                "n_seeds": fv["n_seeds"],
                "target_deg": 36.17,
                "target_sigma_deg": 3.1,
                "protocol": "dynamic AoR, vertical rotating drum "
                            "diam. 150 mm x 25 mm, 5 rpm, 50% fill, "
                            "co-rotating acrylic covers (templates/drum.in; "
                            "axial length halved vs the published 50 mm — "
                            "documented deviation)",
            },
            "bulk_density": {
                "value": round(fv["bulk_density"], 1),
                "calibrated": False,
                "literature": 780,
                "note": "falls out of the fixed PSD + particle density with "
                        "zero calibration — a free consistency check",
            },
        },
        "validation": {
            "scenario": acceptance["scenario"],
            "measured_deg": acceptance["target_deg"],
            "sigma_deg": acceptance["sigma_deg"],
            "criterion": acceptance["criterion"],
            "prestated": True,
            "predicted_deg": verdict["representative"]["predicted_deg"],
            "predicted_std_deg": verdict["representative"]["seed_std"],
            "abs_error_deg": verdict["representative"]["abs_error_deg"],
            "passed": verdict["passed"],
            "family_endpoints_discriminate": verdict["endpoints_discriminate"],
            "deviations": acceptance["prestated_deviations"],
            "verdict_file": "results/phase10-validation/validation_verdict.json",
        },
        "evidence": {
            "ground_truth": GROUND_TRUTH,
            "family_verification": "results/phase9-drum/family_verification.json",
            "valley_check": "results/phase9-drum/valley_check.csv",
            "optimizer_best": "none — the Phase-9 multi-response optimizer "
                              "study was cancelled at the M4 gate (drum "
                              "degenerate with heap); results/phase9-drum/"
                              "best.json is a tombstone for a test artifact "
                              "(invalidated 2026-06-13)",
            "phase9_notes": "results/phase9-drum/NOTES.md",
            "validation": "results/phase10-validation/",
            "lhs_screen": "results/phase7-lhs/lhs_results.csv",
        },
        "reproduction": {
            "command": ".venv/bin/python calibration/material_card.py "
                       "reproduce",
            "n_seeds": 5,
            "tolerance": {"aor": 1.0, "drum": 1.0, "bulk_density": 25.0},
            "note": "tolerances ~= the seed-noise floor: exact on this "
                    "machine's cache; absorbs compiler/MPI nondeterminism "
                    "on a fresh build",
        },
        "scope": {
            "valid_for": [
                "quasi-static and slow-flow bulk behaviour (heaps, slow "
                "drums, hopper drawdown at moderate rates)",
                "wheat-scale spheres at the stated PSD; geometries at the "
                "calibration scale (10^3-10^5 particles)",
            ],
            "not_calibrated_for": [
                "bulk density (uncalibrated consistency check only)",
                "impact/restitution-dominated processes (rest is weakly "
                "constrained)",
                "cohesive or moist material (no cohesion model)",
                "rate-sensitive responses far from the calibrated protocols "
                "(the heap test is strongly lift-speed sensitive)",
            ],
        },
    }
    errors = validate_card(card)
    if errors:
        raise SystemExit("built card fails validation:\n- " + "\n- ".join(errors))
    CARD.parent.mkdir(parents=True, exist_ok=True)
    CARD.write_text(json.dumps(card, indent=2))
    return card


def validate_card(card: dict) -> list[str]:
    """Schema + internal-consistency check. Returns a list of problems
    (empty = valid)."""
    import jsonschema

    errors: list[str] = []
    schema = json.loads(SCHEMA.read_text())
    validator = jsonschema.Draft202012Validator(schema)
    for e in sorted(validator.iter_errors(card), key=str):
        errors.append(f"schema: {'/'.join(str(p) for p in e.path)}: {e.message}")
    if errors:
        return errors

    # internal consistency — things a schema can't see
    anchors = card["equivalence_family"]["anchors"]
    fr = [a["fric"] for a in anchors]
    rf = [a["rollfric"] for a in anchors]
    pf = card["parameters"]["fric"]["value"]
    pr = card["parameters"]["rollfric"]["value"]
    if not min(fr) <= pf <= max(fr):
        errors.append(f"consistency: fric {pf} outside family [{min(fr)}, {max(fr)}]")
    if not min(rf) <= pr <= max(rf):
        errors.append(f"consistency: rollfric {pr} outside family "
                      f"[{min(rf)}, {max(rf)}]")
    for key in card["reproduction"]["tolerance"]:
        if key not in card["responses"]:
            errors.append(f"consistency: reproduction tolerance for {key!r} "
                          "but no recorded response")
    if card["validation"]["passed"] and card["validation"]["abs_error_deg"] is not None:
        tol = (json.loads(ACCEPTANCE.read_text())["multiple"]
               * card["validation"]["sigma_deg"]) if ACCEPTANCE.exists() else None
        if tol is not None and card["validation"]["abs_error_deg"] > tol:
            errors.append("consistency: validation marked passed but "
                          "abs_error exceeds the acceptance tolerance")
    return errors


def reproduce(card: dict, *, n_seeds: int | None = None,
              jobs: int | None = None) -> dict:
    """Replay the card through a fresh runner.evaluate USING ONLY the card's
    contents; compare each calibrated response against the recorded value
    within the card's tolerance. Returns the comparison report."""
    from calibration import runner

    n_seeds = n_seeds or card["reproduction"]["n_seeds"]
    tol = card["reproduction"]["tolerance"]
    params = {k: card["parameters"][k]["value"]
              for k in ("fric", "rollfric", "rest")}
    wall = card["fixed_inputs"]["wall_acrylic"]

    report = {"params": params, "n_seeds": n_seeds, "checks": [], "ok": True}

    def check(name, replayed, recorded, tolerance):
        ok = (replayed is not None
              and abs(replayed - recorded) <= tolerance)
        report["checks"].append({
            "response": name, "replayed": replayed, "recorded": recorded,
            "tolerance": tolerance, "ok": bool(ok)})
        report["ok"] = report["ok"] and bool(ok)

    aor_res = runner.evaluate(params, n_seeds=n_seeds, jobs=jobs,
                              response="aor")
    check("aor", aor_res["aor"], card["responses"]["aor"]["value_deg"],
          tol["aor"])
    check("bulk_density", aor_res["bulk_density"],
          card["responses"]["bulk_density"]["value"], tol["bulk_density"])

    drum_params = {**params, "capfric": wall["fric"], "caproll": wall["rollfric"]}
    drum_res = runner.evaluate(drum_params, n_seeds=n_seeds, jobs=jobs,
                               response="drum")
    check("drum", drum_res["drum_aor"],
          card["responses"]["drum"]["value_deg"], tol["drum"])
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build", help="assemble + validate + write the card")
    vc = sub.add_parser("validate-card", help="schema + consistency check")
    vc.add_argument("--card", type=Path, default=CARD)
    rp = sub.add_parser("reproduce",
                        help="fresh runner.evaluate from ONLY the card")
    rp.add_argument("--card", type=Path, default=CARD)
    rp.add_argument("--seeds", type=int, default=None)
    rp.add_argument("--jobs", type=int, default=None)
    args = ap.parse_args()

    if args.cmd == "build":
        card = build()
        print(json.dumps(card, indent=2))
        print(f"\nOK: card written to {CARD} and schema-valid")
    elif args.cmd == "validate-card":
        errors = validate_card(json.loads(args.card.read_text()))
        if errors:
            print("\n".join(errors))
            raise SystemExit(1)
        print(f"OK: {args.card} is schema-valid and internally consistent")
    else:
        report = reproduce(json.loads(args.card.read_text()),
                           n_seeds=args.seeds, jobs=args.jobs)
        print(json.dumps(report, indent=2))
        if not report["ok"]:
            raise SystemExit(1)
        print("OK: the card reproduces its calibrated responses")


if __name__ == "__main__":
    main()
