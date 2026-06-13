# Phase 10 — Hold-out validation (45° inclined drum) + material card: run record

**Verdict: PASS (2026-06-12, pre-registered criterion).** The representative
calibrated set predicts the never-calibrated 45°-inclined acrylic drum at
**48.93° ± 0.21** (5 seeds) vs the measured **43.65° ± 2.92** (Sugirbay et al.
2022, Table 1) — |error| **5.28° ≤ 2σ₄₅ = 5.84°**, no steadiness warnings,
5/5 seeds. Deliverable shipped: [materials/wheat.json](../../materials/wheat.json)
(schema-valid, `reproduce` exit 0).

## What was run

| Milestone | What | Outcome |
|---|---|---|
| M0 | Re-fetched the Sugirbay 2022 PDF; extracted the full 45° table (per-material reps + ANOVA) into the [ground-truth doc](../../experiments/ground-truth-wheat-literature.md); pre-registered [acceptance.json](acceptance.json) **before any compute** | target acrylic 43.65° ± 2.92 (pooled √MS_within = √8.52, 16 df); criterion ≤ 2σ₄₅ |
| M1 | [templates/drum45.in](../../templates/drum45.in) (gravity-tilt), slab measurement in measure.py, `drum45` runner response, [calibration/validate.py](../../calibration/validate.py), tests | 130 tests green; legacy aor/drum hashes pinned unchanged |
| M2 | 3 smoke iterations at the representative set, seed 1 | SPINUP 4.0 → 5.0 → **7.0 s** (see lessons); final smoke drift-clean 49.13°, frame σ 1.66° |
| M3 | [validate.py](../../calibration/validate.py) run: representative @ 5 seeds + family endpoints @ 2 seeds (9 sims; ~17 min each) | [validation_verdict.json](validation_verdict.json) **PASS**; figure [validation.png](validation.png) |
| M3+ | 50 mm length-sensitivity run (published drum length, NPART 9200, HALFL 0.025) | *(result below)* |
| M4 | [materials/wheat.json](../../materials/wheat.json) + [schema](../../materials/schema.json) via [material_card.py](../../calibration/material_card.py) | schema-valid; `reproduce` replays aor 26.39 / ρ 782 / drum 38.06 from the card alone, all within tolerance |

## Key numbers

- **Representative (fric 0.4001 / μ_r 0.1374 / rest 0.5762):** 48.93° ± 0.21 (5 seeds), error +5.28° (+1.81σ₄₅) — in-band but high.
- **Family endpoints:** low-fric (0.2477/0.2249) → 48.71° ± 0.59; high-fric (0.60/0.1203) → 48.89° ± 0.74. **Family span at 45° = 0.21°** — the inclined drum is family-degenerate exactly as pre-stated (all walls pinned to acrylic → wall-dominated response). The validation validates the *family*, which is the Phase-9 deliverable; it cannot localize within it.
- **Seed noise 0.2–0.7°** ≪ the 5.84° acceptance band (the M2 resolvability gate, retroactively confirmed by the batch).
- **Systematic bias is real and positive (+5.3°),** shared by every anchor. Prime suspect: the halved axial length (25 vs published 50 mm) over-weights the frictional covers, and at 45° the trace is measured *at* the cover. The 50 mm run bounds it:

### 50 mm length-sensitivity run (M3 add-on)

One run at the **published 50 mm length** (NPART 9200, HALFL 0.025, same
representative parameters, seed 49979687; [sens50/](sens50/)): **39.33° ±
2.06 frame σ** over the full 33-frame window, steady tail (last 20 frames)
**39.75° ± 2.24** — a marginal drift flag (+2.3° vs 2se 2.3; the doubled bed
mass relaxes even slower than the 25 mm drum, so treat 39.3–39.8° as the
converged range).

- **The length systematic is ≈ −9.5°** going 25 → 50 mm (48.93° → ~39.5°) —
  roughly an order of magnitude larger than at the vertical drum, confirming
  the pre-stated worry that the halved drum over-weights the covers exactly
  where the 45° trace is measured. It DOMINATES the acceptance band (5.84°).
- **At the published geometry the prediction is 39.3–39.8° vs measured
  43.65° ± 2.92** — error ≈ −3.9 to −4.4° (~1.4σ), also within 2σ.
- **Interpretation:** both geometries pass the pre-stated band, but for
  different reasons; the 25 mm pass (+5.28°) and the 50 mm result (−4.3°)
  bracket the measurement from opposite sides. The fair-geometry comparison
  (50 mm) leaves a residual model-form bias of ~−4° (single spheres + wall
  values calibrated on the source's 7-sphere clumps), comparable to but
  inside the measurement's 2σ. The gating verdict remains the
  pre-registered one (25 mm protocol, documented deviation): **PASS** — and
  the sensitivity run converts the deviation from a caveat into a bounded,
  quantified number.

## Lessons learned

- **The 45° transient is ~2.3× the vertical drum's** (bed climbs until ~7 s of
  rotation vs 3 s): the in-plane gravity component is √2 weaker and the
  wall-dominated bed relaxes slowly. SPINUP 7.0 s; total sim 14.2 s ≈ 17 min/run.
- **The 45° cover-slab flow is intermittent** (avalanche cycle ~2–3 s, frame σ
  ≈ 2–2.7° vs ~1° vertical). Two consequences: the measurement window must
  average ≥ 2 cycles (MEASURE 6.4 s, 33 frames), and the fixed 1°-drift
  steadiness guard false-alarms on cycle phase at steady state — replaced with
  a noise-aware guard (drift must be material AND > 2 se). Sugirbay's own 45°
  acrylic repeats scatter 39.7–46.3°, consistent with intermittency being
  physical.
- **Gravity-tilt beats mesh-tilt** for inclined-drum variants: `region
  cylinder` and primitive walls are axis-aligned only, so tilting g in the
  drum frame reuses every mesh, the insertion region, and the backstops; the
  camera-concentric published measurement maps to a plain x–z fit in a
  cover-adjacent y-slab with **no coordinate transform** (gravity projects
  onto the cover plane along −z).
- **Pre-registration enforced by code worked**: `validate.py run` refuses to
  start without `acceptance.json`; the marginal PASS (1.81σ) is only
  meaningful because 2σ was stated before the first frame was simulated.
- **The CLI `--capfric` default-0.0 footgun** (silently frictionless covers
  under a wrong hash on any drum CLI eval) was found and fixed during M1 —
  override flags now inject only when given.
