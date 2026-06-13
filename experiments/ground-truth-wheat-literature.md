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
| Rotating drum, vertical, 5 rpm (dynamic) | 36.17° (pooled σ ≈ 3.1°) | Sugirbay et al. 2022, Tables 1–2 |

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

## Rotating drum — dynamic AoR (second response, Phase 9)

**TARGET: 36.17° ± 3.1°** — wheat pile dynamic angle of repose in a vertical rotating drum at
5 rpm (Sugirbay et al. 2022, verified against the published PDF on 2026-06-12).

Provenance: single-factor experiment, 4 drum shell materials (soil, steel, PLA, acrylic) ×
5 replications at drum inclination α = 90° (vertical). One-way ANOVA found the shell material
insignificant at vertical (p = 0.68), so the pooled mean **36.17°** is the particle–particle
calibration target. σ ≈ 3.1° is the pooled within-group repeat spread (√MS_within = √9.73 from
their ANOVA Table 2) — a genuine measured spread, unlike the assumed ±1.5° on the static
target. Individual readings span 31.0–44.3°.

### Published drum protocol vs our simulated test

| | Published protocol (Sugirbay et al. 2022) | Our simulated test (Phase 9) |
|---|---|---|
| Drum | inner Ø150 mm × 50 mm length, acrylic cover (transparent end face, rotates with the drum) | Ø150 mm × **25 mm** length — diameter matched (D/d ≈ 40 preserved, the wall-effect regime); axial length halved to fit the run budget. **Covers modeled as co-rotating frictional cap-disk meshes** at the published wheat–acrylic friction (μ_s 0.36 / μ_r 0.29, their Table 11 — note: calibrated with their 7-sphere clumps; carried as a fixed protocol input). A frictionless-cap idealization under-reads the angle by ~5–7° and erases the response (Phase-9 M4 finding); a static frictional cap is unphysical (locks the bed). The halved length over-weights the cover effect relative to their 50 mm drum — documented deviation. |
| Rotation | 5 rpm, clockwise, rolling regime (cascading explicitly avoided); Fr = ω²R/g ≈ 2.1×10⁻³ | **5 rpm** (matched exactly — same Froude number since R is matched) |
| Fill | 50 % of drum volume (by weight-halving), ~9000 clump particles | **50 %** (matched) ≈ 4800 spheres at our fixed PSD |
| Particle model | 7-sphere linear clump, lengths 5.75–7.25 mm (7 sizes, count-weighted) | single spheres 3.4–4.0 mm — **μ_r absorbs shape effects** (the locked Phase-3 modelling decision) |
| Angle extraction | high-speed camera at the cover face, surface points digitized (0.05 mm spacing, OriginPro), linear fit, arctan of slope; average of 4 randomly chosen frames | same idea in-silico: per-frame line fit on the binned free surface in the x–z cross-section, averaged over ~17 steady-state frames |
| Run cost | — | ~7–8.5 min/run, a documented deviation from the repo's 2–5 min guideline (the flowing bed + rotating mesh cost ~2× the heap test per particle-step) |
| Repeats | 5 per material × 4 materials, pooled | 2 seeds per candidate (≥5 on the final set) |

**Method binding:** like the static target, this number is only meaningful tied to its
protocol — vertical drum, 5 rpm, 50 % fill, rolling regime. Their inclined-drum (45°) results
calibrate particle–*material* friction and are not used here.

**Model-form caveat for Phase 9:** the published 36.17° was matched in DEM with 7-sphere
clumps. Our single spheres top out at ~35° *static* AoR over the screened ranges (Phase 7);
whether they can reach a ~36° *dynamic* drum angle inside the parameter box is exactly what
the Phase-9 valley check (M4) must establish before optimizer compute is spent.

## 45° inclined drum — hold-out validation target (Phase 10)

**TARGET: 43.65° ± 2.92°** — wheat pile dynamic angle of repose in the **acrylic** drum
inclined at α = 45°, 5 rpm (Sugirbay et al. 2022, Table 1; verified against the published
PDF on 2026-06-12). **Never used in calibration** — Phases 8–9 calibrated against the
vertical (α = 90°) pooled mean and the static heap only, which is what makes this number a
genuine hold-out for Phase 10.

Provenance (all numbers read directly from the PDF):

- **Table 1, α = 45°, five replications per shell material** (the full row data):
  soil 56.75 / 61.74 / 58.30 / 63.88 / 65.96 (mean **61.32°**);
  steel 45.74 / 46.01 / 46.54 / 48.18 / 45.04 (mean **46.30°**);
  PLA 39.79 / 39.66 / 38.30 / 44.86 / 38.96 (mean **40.31°**);
  acrylic 42.96 / 43.00 / 39.74 / 46.25 / 46.30 (mean **43.65°**).
- **Table 2 ANOVA, α = 45°:** between-groups MS 449.49, F 52.69, **p < 0.001** — at 45° the
  shell material is *strongly significant* (the opposite of vertical, p = 0.68). This is the
  paper's basis for using 45° to calibrate particle–*material* friction, and our basis for
  pinning all wall friction to published values in the hold-out sim (below).
- **σ₄₅ = √MS_within = √8.52 ≈ 2.92°** (16 df) — same pooled within-group convention the
  Phase-9 vertical target uses (√9.73 ≈ 3.1°). The acrylic-row sample SD is 2.74° (4 df);
  the pooled value is adopted for stability and convention-consistency. **Pre-stated before
  any Phase-10 compute:** acceptance criterion |predicted − 43.65°| ≤ 2σ₄₅ = **5.84°**.
- **Protocol identical to the vertical test** ("all the conditions to determine the AOR were
  identical"): 5 rpm rolling regime, 50 % fill by weight-halving, acrylic front cover,
  inner Ø150 mm × 50 mm drum, 5 replications × 4 randomly chosen frames digitized in
  OriginPro (0.05 mm spacing), linear fit, arctan of slope.
- **Measurement geometry at 45°** (Sec. 2.2.2): the camera is **concentric with the tilted
  drum axis** (the pile adjacent to the material is directly visible through the transparent
  cover — no 15° offset as at vertical), and the trace is digitized **adjacent to the material
  side**, i.e. the back face the bed leans on. In a drum-frame simulation that tilts gravity
  instead of the mesh, the camera's image plane *is* the x–z cross-section and gravity projects
  onto it along −z — so the published angle is directly an arctan|dz/dx| line fit in a y-slab
  adjacent to the lower cover, with **no coordinate transform**.
- **Why the acrylic row is the target:** in the acrylic drum the shell, back face, and front
  cover are all acrylic, so every wall in the hold-out sim carries the *same published*
  wheat–acrylic pair μ_s 0.36 / μ_r 0.29 (their Table 11 calibrated particle–material values,
  already carried as the Phase-9 cap protocol input, clump-calibration caveat unchanged).
  Only our calibrated particle–particle set is under test.

### Hold-out protocol deviations (carried from Phase 9, restated for Phase 10)

| Deviation | Consequence at 45° |
|---|---|
| Axial length 25 mm vs published 50 mm | **More biasing than at vertical**: the bed rests *on* the cover and the trace is measured *at* the cover, so the doubled cover-to-volume ratio shapes the measured quantity directly. Bounded by a one-off 50 mm sensitivity run in Phase 10 M3. |
| Single spheres vs 7-sphere clumps | μ_r absorbs shape effects (locked Phase-3 decision); wall values 0.36/0.29 were calibrated on their clumps and are carried as fixed protocol inputs. |
| 2–5 seeds vs 5 physical reps × 4 frames | Seed noise quantified per run; must resolve the 2σ₄₅ = 5.84° band. |

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
| Sugirbay et al. 2022 (7-sphere clump, drum) | 0.15 | 0.36 | — (eliminated) | 36.17° (drum, dynamic) |
| Wang/Zhang (heap AoR) | 0.61 | 0.018 | — | 32.5° |

> ⚠️ **Correction (2026-06-12, Phase-9 M0):** this file previously recorded the Sugirbay drum
> result as "24.3° ± 1.2°" and their calibrated set as 0.52/0.05/0.45 — both were AI-extraction
> artifacts that do not appear anywhere in the paper. Verified against the published PDF: the
> wheat vertical-drum target is **36.17°** and the calibrated particle–particle set is
> **μ_s = 0.15 / μ_r = 0.36** (restitution eliminated; Design-Expert pick from an acknowledged
> valley of equivalent combinations — Sec. 3.4.1: "the goal can be achieved using various
> combinations"). Note their particle model is a **7-sphere linear clump**, not a single sphere,
> so their friction values are not directly comparable to ours.

## Sources

- Boac, Casada, Maghirang, Harner (2010). *Material and Interaction Properties of Selected
  Grains and Oilseeds.* Trans. ASABE 53(4):1201–1216.
- Wang et al. (2023). *Calibration of DEM parameters for wheat.* Food Sci. Nutr. 11:7751–7764
  (lifted-cylinder protocol + EDEM calibrated set).
- Sugirbay et al. (2022). *A Study on the Calibration of Wheat Seed Interaction Properties
  Based on the Discrete Element Method.* Agriculture 12(9):1497.
  https://www.mdpi.com/2077-0472/12/9/1497 *(verified against the published PDF 2026-06-12 —
  earlier AI-extracted values in this file were wrong and have been corrected, see the
  correction note above.)*
- Field-Observed Angles of Repose for Stored Grain in the U.S., Trans. ASABE.
- Scaling of the angle of repose test using upscaled particles, Powder Technol. 2018.
- DEM parameter calibration of cohesive bulk materials, Particuology 2019 (cohesionless-wheat
  confirmation).
