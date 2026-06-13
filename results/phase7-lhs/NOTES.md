# Phase 7 — LHS screen & sensitivity analysis ✅ (Checkpoint 3: GO)

_Completed 2026-06-12._ Latin-hypercube screen over the three calibration knobs, run through the
Phase-6 cached driver, with SALib sensitivity analysis. **45 candidates × 2 seeds = 90 simulation
runs** — within the roadmap's "~50–100 runs" budget. (The screen was planned at 60 candidates; an
overnight run was interrupted by a power-off after 90 of 120 sims had finished, those were salvaged
by re-measuring their dumps, and the final 15 candidates were deliberately **not** run because the
gate conclusions — reachability, dimensionality — were already robust and the only open detail was
a borderline restitution-freeze call that does not change the GO.)

## Deliverables

- Module [calibration/screen.py](../../calibration/screen.py); tests
  [tests/test_screen.py](../../tests/test_screen.py) (8, green; full suite 43 passed).
- [lhs_sample.csv](lhs_sample.csv) — reproducible 60-point LHS (seed 12345).
- [lhs_results.csv](lhs_results.csv) — 45 evaluated candidates (params, aor, aor_std, bulk_density).
- [response_scatter.png](response_scatter.png), [sensitivity.png](sensitivity.png),
  [contact_sheet.png](contact_sheet.png), [sensitivity.json](sensitivity.json).
- Deps `scipy`, `SALib` pinned in [requirements.txt](../../requirements.txt).

## Screen design

Sweeps `fric` 0.20–0.60, `rollfric` **0.00–0.25** (widened past the literature 0.0–0.15 to settle
the Phase-3 μ_r-ceiling worry), `rest` 0.30–0.70; particle-wall friction mirrored. 2 seeds averaged
per candidate. Freeze rule: S1 < 0.05 **and** |Spearman ρ| < 0.25 (the δ estimator has a ~0.06 noise
floor, so first-order Sobol S1 is the discriminator).

## Results — the exit criteria

1. **Sensitivity chart + response scatter exist** (`sensitivity.png`, `response_scatter.png`). ✅
2. **Target bracketed.** AoR spans **0.0–35.0°** (median 24°); 27 ± 1.5° sits in the interior with
   **7 candidates in-band** — bracketed, not clipped at an edge. ✅
3. **Dimension cut to the parameters that matter (≤ 4).** ✅

   | param | δ | Sobol S1 | Spearman ρ |
   |---|---|---|---|
   | **rollfric** | 0.53 | 0.70 | +0.91 |
   | fric | 0.16 | 0.11 | +0.28 |
   | rest | 0.02 | 0.07 | +0.19 |

   Effective dimensionality is **2** (rollfric ≫ fric ≫ rest). rest is practically freezable (ρ and
   δ negligible; S1 0.069 sits just above the strict 0.05 cutoff — Phase 8 may keep it as a cheap
   third dim or freeze it).

## Lessons learned

- **Rolling friction is the dominant AoR lever** — monotone by bin: μ_r 0–0.05 → 9.9°, 0.05–0.10 →
  20.2°, 0.10–0.15 → 24.6°, 0.15–0.20 → 27.3°, 0.20–0.25 → 31.9°. **At μ_r < 0.05 even high sliding
  friction (0.5–0.56) tops out at ~17–19°** — a single-sphere wheat model *cannot* reach 27° without
  substantial rolling friction (shape resistance is absorbed by μ_r). The widened 0.25 ceiling was
  the right call; multisphere is **not** needed.
- **The friction valley is real and quantified.** The 7 in-band candidates span fric 0.25→0.59 at
  rollfric 0.12→0.25 — many (fric, rollfric) pairs give ~27°. A single AoR target yields a valley,
  not a point. This is the empirical justification for Phase 9's second response.
- **Restitution barely matters** for the static heap (ρ +0.19, S1 0.07), exactly as predicted.
- **Objective is trustworthy:** seed noise aor_std median 0.37° (max 1.29°) < 1.5° tolerance; bulk
  density 753–827 kg/m³ straddles the literature ~780 with zero calibration.
- **Driver salvage pattern:** an interrupted batch leaves finished sims unmeasured (measure runs at
  `_finish`, not per-sim). Re-running `runner._finish` with a `status:"ran"` sim dict over the
  existing `*_final.liggghts` dumps banks them as cache hits without re-simulating — recovered 90
  sims here. A plain resume would have wiped and re-run them.

## → Checkpoint 3 — GO (2026-06-12)

- *Target reachable inside parameter ranges?* **Yes** — 27 ± 1.5° bracketed in the interior (7
  in-band of 45), not at an edge.
- *Do ≤ 4 parameters matter?* **Yes — really 2.** rollfric ≫ fric ≫ rest; rest practically freezable.
- *Failure remedies triggered?* **None.** Reachable with the current single-sphere contact model —
  no cohesion, no rolling-friction-variant change, no multisphere. The Phase-3 multisphere worry is
  retired.

**Proceed to Phase 8.** The LHS results are the surrogate seed set; expect a rollfric-led optimum
with fric loosely constrained (the valley) — which is precisely what Phase 9 then breaks.
