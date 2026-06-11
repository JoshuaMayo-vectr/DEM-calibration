# LIGGGHTS 3.8.0 calibration knob catalog

**Build:** arm64 macOS, Open MPI, no VTK — `external/LIGGGHTS-PUBLIC/src/lmp_auto`
**Verified against:** the bundled `doc/*.txt` pages and the Phase-1 tutorial runs in
`results/phase1-tutorials/` (every syntax line below either ran on this binary or is quoted
from its doc page; "Seen in" names the run).

This is the Phase-1 deliverable: every parameter we may calibrate, with its LIGGGHTS
syntax, physical meaning, typical range, and the contact-model choice that activates it.

---

## 1. Contact-model space

### 1.1 The pair_style grammar

```
pair_style gran model {hertz|hooke} tangential {history|no_history} &
    [rolling_friction {cdt|epsd|epsd2|epsd3}] [cohesion {sjkr|sjkr2}]
pair_coeff * *
```

Two rules that bite if forgotten:

1. **Wall fixes must repeat the identical model string**, e.g.
   `fix floor all wall/gran model hertz tangential history rolling_friction epsd2 primitive type 1 zplane 0.0`
   (verified in `06-rollingFriction`, five walls).
2. Primitive walls (`primitive type 1 {zplane|zcylinder|…}`) are **static** — anything that
   must move needs a mesh wall (`fix mesh/surface` + `wall/gran … mesh`) driven by
   `fix move/mesh` (verified in `05-movingMeshGran`).

**Legacy stiffness syntax is out of scope — and not in this build.** The old
`pair_style gran/hertz/history <k_n> …` form is rejected with `Invalid pair style`
(`02-contactModels/in.oldModels`). The `gran_model_*_stiffness` doc pages can be ignored.

### 1.2 Decision table: model choice → required property/global knobs

| pair_style component | Requires (`fix property/global …`) | Notes |
|---|---|---|
| `model hertz` | `youngsModulus`, `poissonsRatio`, `coefficientRestitution`, `coefficientFriction` | stiffness from Hertzian contact theory |
| `model hooke` | same as hertz **plus** `characteristicVelocity` (scalar) | linear spring; the extra arbitrary scalar argues against it |
| `tangential history` | (no extra knobs) | Mindlin tangential spring with sliding memory — **required** for meaningful friction calibration |
| `tangential no_history` | (no extra knobs) | tangential damping only, no spring — not suitable for quasi-static heaps |
| `rolling_friction cdt` | `coefficientRollingFriction` | constant directional torque |
| `rolling_friction epsd` | `coefficientRollingFriction`, `coefficientRollingViscousDamping` | elastic-plastic spring-dashpot |
| `rolling_friction epsd2` | `coefficientRollingFriction` **only** | EPSD variant: k_r tied to tangential stiffness, viscous damping torque **disabled** |
| `rolling_friction epsd3` | `coefficientRollingFriction`, `coefficientRollingViscousDamping`, `coeffRollingStiffness` (scalar) | most knobs, least used |
| `cohesion sjkr` | `cohesionEnergyDensity` | exact sphere–sphere intersection contact area |
| `cohesion sjkr2` | `cohesionEnergyDensity` | simplified contact area A = 2π·δₙ·(2R*) |

### 1.3 Our default for Phase 3 (rationale)

```
pair_style gran model hertz tangential history rolling_friction epsd2
```

- **hertz** over hooke: no `characteristicVelocity` to justify; standard in published
  calibration work.
- **tangential history**: the heap is friction-dominated and quasi-static; the tangential
  spring memory is what makes sliding friction physically meaningful.
- **epsd2** over cdt/epsd/epsd3: one knob (`coefficientRollingFriction`), no extra damping
  coefficient to fix arbitrarily, widely used (Ai et al. 2011 model). Proven on this build
  with a strong monotonic pile response (`06-rollingFriction`: μ_r 0.05 → flat spread;
  μ_r 0.5 → 23 mm conical pile).
- **`cohesion sjkr` appended only if** the Phase-2 material proves cohesive — it is a pure
  two-line toggle (pair_style suffix + one property/global line), verified in `03-cohesion`.

---

## 2. Per-knob catalog

Roles: **TARGET** = searched by the optimizer · **FIXED INPUT** = measured, never calibrated ·
**NUMERICAL DEVICE** = set for tractability, documented, not physical.

### coefficientFriction — sliding (static) friction μ_s

- **Syntax:** `fix m4 all property/global coefficientFriction peratomtypepair 1 ${FRIC}` (pair: particle–particle and, with more atom types, particle–wall)
- **Activated by:** every `gran model` variant (tangential force cap μ·Fₙ)
- **Physical meaning:** Coulomb friction limit on the tangential contact force — the primary brake on inter-particle sliding; first-order control on angle of repose.
- **Legal range:** ≥ 0 (doc); values > ~1.2 rarely physical
- **Literature-typical:** 0.1–1.0 (project working range, ROADMAP Phase 7). Calibrated grain values: wheat–wheat 0.3 (Agriculture 12:1497, 2022); maize–maize ≈ 0.2–0.5 across studies (Coetzee 2017 review).
- **Calibration role:** **TARGET (primary)**
- **Doc ref:** `doc/gran_model_hertz.txt` · **Seen in:** all runs; varied in `06-rollingFriction` (0.5)

### coefficientRollingFriction — rolling resistance μ_r

- **Syntax:** `fix m5 all property/global coefficientRollingFriction peratomtypepair 1 ${ROLLFRIC}`
- **Activated by:** any `rolling_friction` choice (cdt/epsd/epsd2/epsd3)
- **Physical meaning:** resistive torque opposing relative rolling — the sphere-model proxy for particle angularity/shape. Second first-order control on heap angle; the (μ_s, μ_r) pair is the expected degeneracy valley.
- **Variant-specific meaning:** cdt = constant torque μ_r·R*·Fₙ; epsd/epsd2 = elastic-plastic spring torque saturating at μ_r·R*·Fₙ (epsd2 ties rolling stiffness to tangential stiffness k_r = k_t·R*², no viscous term); epsd3 adds tunable stiffness. Calibrated μ_r values are **not portable between variants** — the catalog and material card must name the variant.
- **Legal range:** ≥ 0
- **Literature-typical:** 0.0–0.5 (project working range). Calibrated grain values: wheat–wheat 0.04 (Agriculture 12:1497); maize seed–seed 0.03 (Processes 9:914, 2021); irregular maize via drum test up to ~0.1–0.3 (Front. Agric. Sci. Eng. drum study).
- **Calibration role:** **TARGET (primary)**
- **Doc ref:** `doc/gran_rolling_friction_{cdt,epsd,epsd2,epsd3}.txt` · **Seen in:** `06-rollingFriction` (0.05 / 0.5)

### coefficientRestitution — restitution e

- **Syntax:** `fix m3 all property/global coefficientRestitution peratomtypepair 1 ${REST}`
- **Activated by:** hertz and hooke (sets the contact damping)
- **Physical meaning:** kinetic-energy retention in a binary impact; controls how quickly pouring particles calm down. Weak influence on the *static* final heap — strong influence on settling time.
- **Legal range:** 0 < e ≤ 1 (e = 0 undefined damping; doc requires > 0)
- **Literature-typical:** 0.1–0.9 (project working range). Grain impact studies: wheat ≈ 0.5, maize ≈ 0.2–0.6 depending on impact surface and moisture (Coetzee 2017; maize energetic-restitution study, Powder Technol. 2019).
- **Calibration role:** **TARGET (weak for static heap — expect Phase 7 to freeze it)**
- **Doc ref:** `doc/gran_model_hertz.txt` · **Seen in:** all runs (0.3–0.95)

### cohesionEnergyDensity — SJKR cohesion k

- **Syntax:** `fix m6 all property/global cohesionEnergyDensity peratomtypepair 1 ${COHED}` (J/m³)
- **Activated by:** `cohesion sjkr` or `cohesion sjkr2`
- **Physical meaning:** adds attractive normal force F = k·A over the contact area A — the simplified JKR adhesion model. sjkr computes A as the exact sphere–sphere intersection; sjkr2 linearizes it (A = 2π·δₙ·2R*), cheaper and smoother near detachment.
- **Legal range:** ≥ 0 (0 ≡ off; prefer omitting the model entirely)
- **Literature-typical:** 0 for dry free-flowing grain. When used: ~10²–10⁶ J/m³ depending on material and moisture; the tutorial's 3e5 J/m³ visibly clumps 1.5 mm glass-density spheres (`03-cohesion`: settled bed ~3× looser, contact count doubled, runtime ~3×).
- **Calibration role:** **TARGET (conditional — enters only if Phase 2's material demands it)**
- **Doc ref:** `doc/gran_cohesion_sjkr.txt`, `doc/gran_cohesion_sjkr2.txt` · **Seen in:** `03-cohesion`

### youngsModulus — contact stiffness E

- **Syntax:** `fix m1 all property/global youngsModulus peratomtype 5.e6`
- **Activated by:** hertz and hooke
- **Physical meaning:** elastic modulus entering contact stiffness. In DEM calibration practice it is **deliberately softened 2–3 orders of magnitude below the real material** so the Rayleigh-stable timestep stays workable; quasi-static bulk responses (heap angle, packing) are insensitive to it above ~1e7 Pa (Coetzee 2017, §4).
- **Legal range:** **LIGGGHTS enforces E > 5e6 Pa in SI units** (`gran_model_hooke.txt:137`) — the hard floor for softening.
- **Literature-typical (softened):** 1e7–1e8 Pa for grain simulations (real wheat/maize kernel E ≈ 1e8–1e10).
- **Calibration role:** **NUMERICAL DEVICE** — fixed per study, stated on the material card; never optimized.
- **Doc ref:** `doc/gran_model_hertz.txt` · **Seen in:** all runs (5e6)

### poissonsRatio — ν

- **Syntax:** `fix m2 all property/global poissonsRatio peratomtype 0.45`
- **Activated by:** hertz and hooke
- **Physical meaning:** enters effective contact stiffness ratios; bulk-response sensitivity is weak.
- **Legal range:** 0 < ν < 0.5
- **Literature-typical:** 0.2–0.45; grain studies commonly 0.25–0.4.
- **Calibration role:** **FIXED INPUT** (pick a literature value for the material, document it)
- **Doc ref:** `doc/gran_model_hertz.txt` · **Seen in:** all runs (0.45)

### coefficientRollingViscousDamping

- **Syntax:** `fix id all property/global coefficientRollingViscousDamping peratomtypepair 1 0.1`
- **Activated by:** `rolling_friction epsd` and `epsd3` **only** — *not* epsd2 (epsd2 disables the viscous rolling torque; supplying this knob for epsd2 is unnecessary).
- **Physical meaning:** dashpot on relative rolling velocity; numerical smoothing of rolling oscillations.
- **Literature-typical:** small constant (~0.05–0.3) when the variant requires it.
- **Calibration role:** **FIXED INPUT** (small constant) — avoid by choosing epsd2/cdt.
- **Doc ref:** `doc/gran_rolling_friction_epsd.txt` · **Seen in:** — (epsd2 path verified without it)

### characteristicVelocity

- **Syntax:** `fix m5 all property/global characteristicVelocity scalar 2.`
- **Activated by:** `model hooke` only (sets the linear stiffness from an expected impact velocity)
- **Physical meaning:** velocity scale used to back out the spring constant; an arbitrary modeling input with no measurable counterpart — the main reason our templates use Hertz.
- **Calibration role:** **NUMERICAL DEVICE** (avoided entirely under Hertz)
- **Doc ref:** `doc/gran_model_hooke.txt` · **Seen in:** `04-meshGran`, `05-movingMeshGran` (2.0)

### Particle density and radius / PSD

- **Syntax:** `fix pts1 all particletemplate/sphere <seed> atom_type 1 density constant 2500 radius constant 0.0025`
  + `fix pdd1 all particledistribution/discrete <seed> N pts1 w1 [pts2 w2 …]` (multiple templates ≈ discrete PSD)
- **Physical meaning:** directly measurable material inputs.
- **Calibration role:** **FIXED INPUT** — measured in Phase 2 (pycnometer / sieving), never calibrated. If runtime forces particle upscaling (coarse-graining), the scale factor is a stated assumption, not a fit parameter.
- **Doc ref:** `doc/fix_particletemplate_sphere.txt`, `doc/fix_particledistribution_discrete.txt` · **Seen in:** all runs

---

## 3. Simulation-control knobs relevant to calibration

### timestep + fix check/timestep/gran

- **Syntax:** `timestep 0.00001` · `fix ts all check/timestep/gran 1000 0.1 0.1`
  with `f_ts[1]` (fraction of Rayleigh dt) and `f_ts[2]` (fraction of Hertz dt) in
  `thermo_style custom …` — warns when a fraction exceeds its threshold.
- **Practice:** keep dt below ~10–20 % of the Rayleigh time at the **softened** E and the
  **smallest** particle radius. Verified in `04-meshGran`: dt = 5e-5 s, E = 5e6, r = 5 mm →
  f_Rayleigh = 0.079, f_Hertz = 0.043, no warnings. Phase 3's exit criterion requires this
  check to pass in the AoR template.
- **Doc ref:** `doc/fix_check_timestep_gran.txt`

### Insertion seeds — the stochasticity lever

- **Syntax:** the `seed` arguments of `particletemplate/sphere`, `particledistribution/discrete`,
  `insert/pack` / `insert/stream` (must be primes per the docs; tutorials use 15485863, 15485867, 32452843).
- **Role:** same parameters + different seeds → different packing → slightly different heap
  angle. This is exactly the noise floor Phase 4 must quantify (≥ 5 seeds) and Phase 6's
  runner must average over. Seeds enter via `-var` like everything else.

### Command-line variables (the pipeline mechanism)

- **Syntax in template:** `variable MUR index 0.3` (default) + `${MUR}` at the point of use.
- **Invocation:** `lmp_auto -in template.in -var MUR 0.05 -var TAG low -log log.low`
- Verified end-to-end in `06-rollingFriction`, including `${TAG}` inside dump filenames to
  keep concurrent trial outputs separate — the exact pattern Phase 6's runner builds on.

### Neighbor settings

- `neighbor 0.002 bin` (skin ≈ particle radius is the tutorials' habit) and
  `neigh_modify delay 0`. Affects speed, not physics; retune only if profiling says so.

---

## 4. Calibration summary table

| Knob | Role | Working range (Phase 7) | Cited grain values |
|---|---|---|---|
| coefficientFriction | TARGET | 0.1–1.0 | wheat–wheat 0.3; maize 0.2–0.5 |
| coefficientRollingFriction | TARGET | 0.0–0.5 | wheat 0.04; maize 0.03–0.3 (variant-dependent) |
| coefficientRestitution | TARGET (likely frozen) | 0.1–0.9 | wheat ≈ 0.5; maize 0.2–0.6 |
| cohesionEnergyDensity | TARGET (conditional) | 0 unless Phase 2 demands | dry grain: 0 |
| youngsModulus | NUMERICAL DEVICE | fixed 1e7–1e8 Pa (floor 5e6) | — |
| poissonsRatio | FIXED INPUT | fixed 0.25–0.4 | — |
| density, PSD | FIXED INPUT | measured (Phase 2) | — |

**References**

- Coetzee, C.J. (2017). *Review: Calibration of the discrete element method.* Powder Technology 310, 104–142.
- Coetzee, C.J. (2020). *Calibration of the discrete element method: Strategies for spherical and non-spherical particles.* Powder Technology 364, 851–878.
- Ai, J., Chen, J.-F., Rotter, J.M., Ooi, J.Y. (2011). *Assessment of rolling resistance models in discrete element simulations.* Powder Technology 206(3), 269–282. (EPSD2 source, cited by the LIGGGHTS doc.)
- *A Study on the Calibration of Wheat Seed Interaction Properties Based on the Discrete Element Method.* Agriculture 12(9), 1497 (2022).
- *DEM Parameter Calibration of Maize Seeds and the Effect of Rolling Friction.* Processes 9(6), 914 (2021).
- LIGGGHTS-PUBLIC 3.8.0 bundled documentation, `external/LIGGGHTS-PUBLIC/doc/`.
