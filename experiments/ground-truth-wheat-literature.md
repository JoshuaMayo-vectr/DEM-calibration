# Ground Truth — Wheat Grain (Literature Substitute for Phase 2)

> ⚠️ **Phase 2 physical measurement was skipped — no physical sample is available.**
> The numbers below are **published literature values for wheat grain**, standing in for
> measured ground truth so that Phases 3–10 have a calibration target. They are sourced and
> cross-checked, but they are **not measurements taken on our material**. In particular the
> angle-of-repose spread **σ is assumed (±1.5°), not measured** — it is the calibration
> tolerance, and nothing downstream can be more accurate than it. If a physical sample later
> becomes available, this file is what Phase 2 replaces.

**Material:** common wheat (*Triticum aestivum*), dry, storage moisture ≈ 10–14 % w.b.
**Date assembled:** 2026-06-11.

## Measured-equivalent values (the calibration inputs and target)

| Quantity | Value | Confidence | Primary source(s) |
|---|---|---|---|
| Kernel dimensions (L × W × T) | ~6.0 × 3.0 × 2.6 mm | high | Boac et al. 2010 |
| **Equivalent sphere diameter** | **3.8 mm** representative; spread 3.4–4.0 mm | good | Boac et al. 2010; Wang et al. 2023 |
| **Particle (kernel) density** | **1400 kg/m³** | high | Sugirbay et al. 2022; Boac et al. 2010 (range 1290–1430) |
| **Poured bulk density** | **~780 kg/m³** | high (moisture-sensitive) | Boac et al. 2010 (690–823); test weight HRW ≈ 772 |
| **Static angle of repose (TARGET)** | **27° ± 1.5°** (lifted-cylinder method) | low–medium (method-sensitive) | see method note below |

### Angle of repose — method binding (read before using the target)

AoR for wheat is **strongly method-dependent** — this is the single biggest caveat:

| Method | Value | Source |
|---|---|---|
| Field-observed piling (stored HRW) | ~22° | Field-Observed Angles of Repose, Trans. ASABE |
| Filling / piling ("dynamic") | ~16° | Boac et al. 2010 |
| Funnel / emptying ("static") | 24–38° | Boac et al. 2010 |
| Lifted-cylinder (EDEM-validated) | 31.7° | Wang et al. 2023 |
| Rotating drum | 24.3° ± 1.2° | Sugirbay et al. 2022 |

We calibrate against the **lifted-cylinder method** to match our simulated test. The chosen
target **27° ± 1.5°** sits in the lower-middle of the cylinder/pouring cluster. The target is
only meaningful tied to this one method — **do not compare against funnel (~32°) or field
(~22°) values.**

## Physical test protocol (literature) and our simulated deviation

| | Published protocol (Wang et al. 2023) | Our simulated test (Phase 3) |
|---|---|---|
| Rig | bottomless cylinder Ø27 mm × 190 mm | Ø80 mm × 100 mm (≈3× — AoR is rig-size invariant when quasi-static; Ø27 mm holds too few particles for a clean flank) |
| Fill | 30 g wheat | ~150 g (4000 particles) |
| Lift speed | 10 mm/s | **10 mm/s** (matches the protocol). The Phase-3 sensitivity check found AoR strongly rate-dependent (18.4° @10 vs 12.3° @25 vs 10.4° @50 mm/s), so we lock to the literature protocol speed rather than a faster compromise. The 10 mm/s run is ~3.9 min — within the 5-min budget. |
| Repeats | 10 | 3 seeds (Phase 4 quantifies the seed noise floor) |

**AoR is strongly lift-speed sensitive** for this single-sphere system and is *not*
quasi-static-invariant at the speeds tested (cf. Scaling of the angle of repose test,
Powder Technol. 2018). The Phase-3 one-off check (10/25/50 mm/s) showed a 6° swing between 10
and 25 mm/s — so we run at the published 10 mm/s, and the simulated test mirrors the physical
protocol. Any residual rate effect is then shared between sim and (literature) measurement.

## Fixed (non-calibrated) parameters

| Parameter | Value | Why fixed |
|---|---|---|
| Young's modulus (E) | **1×10⁷ Pa** (softened) | Numerical device — real wheat is O(10²–10³ MPa); AoR insensitive over 1e7–1e8; softening widens the timestep. LIGGGHTS enforces E > 5e6. |
| Poisson ratio (ν) | 0.25 | Weak bulk-response effect; literature 0.25–0.42 |
| Cohesion | **0 (cohesionless, no SJKR)** | Dry wheat at storage moisture is cohesionless in the DEM literature (Particuology 2019). SJKR also costs ~3× runtime. |
| Particle density | 1400 kg/m³ | Directly measurable input, never calibrated |
| PSD | discrete 3.4 / 3.7 / 4.0 mm, mass weights 0.25/0.50/0.25 | Distribution suppresses crystalline packing artifacts vs mono-sized |

## Calibration parameter search ranges (for the LHS screen / optimizer)

| DEM parameter | Range | Notes |
|---|---|---|
| Sliding friction, particle–particle (μ_s,pp) | 0.20 – 0.60 | primary AoR driver; lit cluster 0.30–0.55 |
| Sliding friction, particle–wall (μ_s,pw) | 0.20 – 0.60 | lit 0.25–0.79 (widen upper to 0.7 if a steel wall matters) |
| Rolling friction, epsd2 (μ_r) | 0.00 – 0.15 | calibrated wheat 0.018–0.05; widened upper because single spheres must absorb shape effects |
| Restitution (e) | 0.30 – 0.70 | weak effect in quasi-static lift; lit 0.45–0.60 |

## Published calibrated wheat sets (cross-checks, not inputs)

These are independent published calibrations — use to sanity-check that our pipeline lands in
a plausible region, **not** as parameter values to copy.

| Source | μ_s,pp | μ_r,pp | e_pp | Reported AoR |
|---|---|---|---|---|
| Wang et al. 2023 (EDEM) | 0.30 | 0.04 | 0.50 | 31.7° |
| Sugirbay et al. 2022 | 0.52 | 0.05 | 0.45 | 24.3° |
| Wang/Zhang (heap AoR) | 0.61 | 0.018 | — | 32.5° |

## Sources

- Boac, Casada, Maghirang, Harner (2010). *Material and Interaction Properties of Selected
  Grains and Oilseeds.* Trans. ASABE 53(4):1201–1216.
- Wang et al. (2023). *Calibration of DEM parameters for wheat.* Food Sci. Nutr. 11:7751–7764
  (lifted-cylinder protocol + EDEM calibrated set).
- Sugirbay et al. (2022). *Calibration of Wheat Seed Interaction Properties Based on DEM.*
  Agriculture 12(9):1497. *(some values AI-extracted from PDF — verify against source table
  before treating as a hard anchor.)*
- Field-Observed Angles of Repose for Stored Grain in the U.S., Trans. ASABE.
- Scaling of the angle of repose test using upscaled particles, Powder Technol. 2018.
- DEM parameter calibration of cohesive bulk materials, Particuology 2019 (cohesionless-wheat
  confirmation).
