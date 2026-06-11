# Phase 3 — Parameterized angle-of-repose template: run record

**Date:** 2026-06-11 · **Deliverable:** [templates/aor.in](../../templates/aor.in)
**Material:** wheat grain, literature ground truth ([experiments/ground-truth-wheat-literature.md](../../experiments/ground-truth-wheat-literature.md))

The template fills an open-ended mesh cylinder with wheat-scale spheres, settles, lifts the
cylinder via `fix move/mesh`, relaxes to a heap, and writes a final `dump custom`. All
calibration parameters enter as `-var`. See the file header for the full variable list.

## Configuration (locked)

| | value |
|---|---|
| Contact model | `gran model hertz tangential history rolling_friction epsd2`, no cohesion |
| Atom types | 1 = particles, 2 = walls (floor + side primitives + mesh cylinder) |
| PSD (fixed) | discrete d = 3.4 / 3.7 / 4.0 mm, mass weights 0.25 / 0.50 / 0.25 |
| Particle density | 1400 kg/m³ |
| Young's modulus | 1×10⁷ Pa (softened), ν = 0.25 |
| Timestep | 8×10⁻⁶ s → Rayleigh fraction 0.0734 (check passes, 0 dangerous builds) |
| Geometry | cylinder R = 0.040 m, H = 0.100 m; 4000 particles (~146 g); box ±0.14 m, z 0–0.20 |
| Lift | 10 mm/s over 0.055 m (matches Wang 2023 protocol) |
| Stages | settle 0.4 s (50k) · lift 5.5 s (688k) · relax 0.4 s (50k) |

## Exit criterion — MET

Validation triplet via [run_triplet.sh](run_triplet.sh), identical seed, REST 0.5,
FRICPW=FRIC, ROLLFRICPW=ROLLFRIC, crude angles via [crude_angle.py](crude_angle.py)
(flank fit — Phase 4 owns the real measurement). Profiles: [triplet_profiles.png](triplet_profiles.png).

| TAG | FRIC | μ_r | crude AoR | peak | base_r | wall time | Rayleigh | retained |
|---|---|---|---|---|---|---|---|---|
| low | 0.20 | 0.00 | ~0° (flat pancake) | 2.0 mm | 159 mm | 165 s | 0.073 | 4000/4000 |
| med | 0.40 | 0.05 | 18.4° | 22.8 mm | 69 mm | 233 s | 0.073 | 4000/4000 |
| high | 0.60 | 0.15 | 26.1° | 31.6 mm | 60 mm | 226 s | 0.073 | 4000/4000 |

- **Visibly different, monotonic steepening** ✓ (angle and peak rise, base shrinks with friction)
- **Each run ≤ 5 min** ✓ (max 3.9 min)
- **Timestep check passes at softened E** ✓ (Rayleigh fraction 0.073 < 0.1, 0 dangerous builds, all runs settle to a static heap — relax KE ≤ 1e-7 J)

## Sensitivity one-offs (at med params: FRIC 0.4, μ_r 0.05)

**Young's modulus** — E = 1e7 → 12.9° vs E = 5e7 → 12.3°* (Δ ≈ 0.6° < 1°). E = 1e7 confirmed
AoR-insensitive; we keep it because it doubles the workable timestep (halves runtime). The
5e7 run needed dt = 3.5e-6 (Rayleigh 0.072).
*(measured at 25 mm/s — the comparison is internally consistent at that speed.)*

**Lift speed** — **strongly rate-sensitive, NOT quasi-static-invariant:**

| lift speed | crude AoR |
|---|---|
| 10 mm/s | 18.4° |
| 25 mm/s | 12.3° |
| 50 mm/s | 10.4° |

6° swing between 10 and 25 mm/s. We **lock to 10 mm/s** (the published wheat protocol, Wang
2023) rather than a faster compromise — the simulated test then mirrors the physical protocol,
so any residual rate effect is shared between sim and (literature) measurement. The 10 mm/s
run is ~3.9 min, within budget.

## Checkpoint-3 preview (flag for Phase 7)

At the **top** of the LHS ranges (FRIC 0.6, μ_r 0.15) the crude angle reaches **26.1°** —
within ~1° of the 27° ± 1.5° literature target. At published friction (med ≈ Wang/Sugirbay
values) it is only 18.4°. So:

- The target appears **reachable but only near the high-μ_r corner** of the ranges. Single
  spheres under-predict AoR and rolling friction must absorb the missing shape resistance
  (as the literature warned). **Phase 7 should expect the optimum to sit at high μ_r and may
  need to widen the μ_r ceiling above 0.15** — or accept multisphere particles if 27° proves
  unreachable. This is exactly what Checkpoint 3 exists to decide.
- The crude flank fit under-reads the true repose angle (it includes the rounded toe); the
  tested Phase-4 measure will read somewhat higher, improving the margin.

## Gotchas hit (carry into Phase 6 runner design)

1. **Mesh path cannot contain spaces.** A `-var MESH` value is re-tokenized by the LIGGGHTS
   input parser, which splits on whitespace — and the repo root is `…/09 DEM-calibration`.
   Pass a **space-free relative path** (resolved from the run's cwd), never the absolute path.
   The `-in <template>` arg is fine with spaces (shell passes it as one arg).
2. **All five RNG seeds must be distinct** (3 templates + distribution + insert). LIGGGHTS
   aborts otherwise. The three template seeds and the distribution seed are fixed distinct
   primes in the template; only the insertion `SEED` is exposed (the seed-to-seed noise lever).
3. **Whitelist warning is benign** — our contact model isn't in the compiled whitelist, so it
   runs ~20% slower (unoptimized). Not worth recompiling for calibration-scale runs.
4. **Cost datum for the optimizer budget:** ~6.9e-8 s per particle-step on 2 MPI ranks
   (4000 particles, 788k steps at 10 mm/s → ~230 s). Faster per particle-step than the
   Phase-1 datum (1.18e-7); the 5-min budget holds with headroom.

## Reproduce

```
bash results/phase3-aor/run_triplet.sh          # low/med/high + crude angles
# single run:
cd results/phase3-aor/smoke && mpirun -np 2 \
  ../../../external/LIGGGHTS-PUBLIC/src/lmp_auto -in ../../../templates/aor.in \
  -var MESH ../../../templates/meshes/cylinder_r0.040_h0.100.stl -var TAG smoke
```
