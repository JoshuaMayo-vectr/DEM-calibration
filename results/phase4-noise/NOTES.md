# Phase 4 — Automated measurement module: run record

Module: [calibration/measure.py](../../calibration/measure.py) · tests: [tests/test_measure.py](../../tests/test_measure.py) · this study: [run_seeds.sh](run_seeds.sh)

## What the module does

`measure_heap(final_dump, settled_dump)` returns `aor_deg`, `bulk_density_kgm3`
(+ diagnostics) and always emits a two-panel audit figure
(`*_profilefit.png`): profile fit on the left, equal-aspect 10-mm-gridded side
view on the right for manual verification.

**Angle algorithm (two-stage).** Stage 1: radial bins of one median particle
diameter; per-bin surface = flier-robust "supported max" of particle tops
(z + radius); OLS on bins whose surface height lies in 0.2–0.8 × peak (the
image-analysis convention that excludes the rounded tip and toe). Stage 2
("shell refinement"): OLS over **all** particle tops within ±0.75 diameter of
the stage-1 line — a constant-thickness surface shell, which cancels the
bin-population-dependent extreme-value bias that tilts pure binned fits
(~0.8° on synthetic cones). Flat heaps (< 4 diameters tall) fall back to a
radius window (`radial_window_flat`) and read a continuous ≈ 0°. Four
azimuthal-quadrant refits give `aor_sector_std` as a per-measurement asymmetry
diagnostic.

**Bulk density.** On the settle-end frame (`*_50000.liggghts`, cylinder still
down): interior-slab estimate, z ∈ [2d, h_fill − 2d], mass of centers in slab
over slab volume — excludes the loose free surface and floor layer. The naive
total (M / π R² h_fill) is reported as a cross-check; it runs ~7% lower
systematically (it includes the surface region).

## Exit criterion 1 — synthetic heaps ±0.5°

`pytest tests/` — **13 passed** (cones 15/25/30°, truncated cone, flat disc,
1% fliers, rounded toe, known-packing density, real-dump parsing/regression,
audit-plot emission, sector diagnostic).

Accuracy beyond the fixtures (volume-matched cones, 10 seeds × angles
12–30°): mean |error| ≈ 0.26°, worst single case 0.6°. Below ~10° the heap is
only a few particle layers tall and accuracy degrades gracefully (mean −0.4°
at 8°) — irrelevant at the 27° target, noted for completeness.

## Exit criterion 2 — manual agreement ±1°

Rise/run read off the 10-mm grid of the side-view panel (red flank line over
the particle silhouette):

| run | automated | manual grid readout | Δ |
|---|---|---|---|
| med  | 19.23° | ≈ 21 mm / 61 mm → 19.0° | 0.2° |
| high | 28.89° | ≈ 16 mm / 30 mm → 28.1° | 0.8° |

Both within ±1°. Artifacts committed here: [med_final_profilefit.png](med_final_profilefit.png),
[high_final_profilefit.png](high_final_profilefit.png) (generated from the
phase-3 med/high final dumps; regenerate with `calibration/measure.py`).

## Exit criterion 3 — seed noise floor < σ = 1.5°

Five insertion seeds (`-var SEED`, the only exposed RNG lever) at the **high**
set FRIC = 0.6 / ROLLFRIC = 0.15 / REST = 0.5 — the near-target corner where
the optimizer will operate.

| seed | AoR [°] | sector std [°] | bulk ρ [kg/m³] | wall time |
|---|---|---|---|---|
| 49979687  | 28.89 | 0.71 | 759 | 3.8 min |
| 67867967  | 28.44 | 0.76 | 764 | 3.9 min |
| 86028121  | 29.19 | 0.97 | 761 | 4.0 min |
| 104395301 | 30.40 | 1.03 | 753 | 3.9 min |
| 122949823 | 30.06 | 0.95 | 761 | 3.9 min |

**Mean 29.40° · σ_seed 0.82° · range 1.96°** (bulk ρ: 760 ± 4 kg/m³ — seed
noise on density is negligible).

**Verdict: σ_seed = 0.82° < 1.5° = physical σ — exit criterion 3 met.** The
noise floor is roughly half the target tolerance; averaging 2 seeds per
candidate (σ/√2 ≈ 0.6°) is comfortable for the optimizer, 3 if conservative.
All ten audits clean (settle KE ≤ 3.5e-9 J, relax KE ≤ 1.1e-13 J; 4000/4000
particles inserted every run).

(Contingency if σ_seed ≥ 1.5° — average more seeds per candidate or enlarge
the heap — not needed.)

## Regression vs the Phase-3 crude baseline

All seven existing final dumps (crude = `results/phase3-aor/crude_angle.py`,
which under-reads by fitting r ∈ [0.3, 0.8]·rmax — a window that includes the
rounded toe). med and lift10 are the same run configuration.

| run | crude | phase 4 | sector std | bulk ρ slab / total |
|---|---|---|---|---|
| low    | ~0°   | −0.00° (flat method) | 0.01° | 834 / 779 |
| med    | 18.4° | 19.23° | 0.51° | 799 / 745 |
| high   | 26.1° | **28.89°** | 0.71° | 759 / 711 |
| lift10 | 18.4° | 19.23° | 0.51° | 799 / 745 |
| lift50 | 10.4° | 11.33° | 0.37° | 799 / 745 |
| E5e7   | 12.9° | 13.45° | 0.46° | 792 / 734 |
| smoke  | 12.3° | 13.01° | 0.37° | 799 / 745 |

Ordering and rate-sensitivity findings from Phase 3 are preserved; every
toe-free angle reads above crude, as predicted in the Phase-3 handoff note.

**Checkpoint-3 implication.** With the toe-free measurement, the high set
reads **29.4° ± 0.8°** (5-seed mean) — it now *overshoots* the 27° ± 1.5°
target, which sits comfortably between med (19.2°) and high (29.4°), inside
the explored range rather than at its corner (crude had high at 26.1°,
i.e. the target at the extreme edge). The "widen μ_r ceiling above 0.15"
question (ROADMAP open questions) loses urgency: published-range parameters
bracket the target without widening.

**Bulk density sanity.** Settled-state slab densities 759–834 kg/m³ across
runs vs the literature poured bulk density ≈ 780 kg/m³ — the fixed inputs
(PSD, particle density) land the packing in the right range with no
calibration, as expected for spheres at φ ≈ 0.55–0.6.
