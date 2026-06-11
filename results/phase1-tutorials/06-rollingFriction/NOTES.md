# 06-rollingFriction — Phase 1 smoke test (not a bundled tutorial)

**Why this exists:** none of the five bundled Phase-1 tutorials exercises `rolling_friction`,
yet `coefficientRollingFriction` is a primary calibration target. This derived script proves
the exact pair_style string and knob on **this** build before they're enshrined in the knob
catalog and the Phase-3 template. It also dry-runs the `-var` command-line mechanism the
whole pipeline is built on.

**Date:** 2026-06-11 · **Commands:**

```
mpirun -np 2 lmp_auto -in in.rollingFriction -var MUR 0.05 -var TAG low  -log log.low    # 5.8 s
mpirun -np 2 lmp_auto -in in.rollingFriction -var MUR 0.5  -var TAG high -log log.high   # 8.5 s
```

Both ✅ normal completion. Setup: 1500 spheres (r = 2.5 mm, ρ = 2500) dropped from a narrow
column onto a plate, `hertz tangential history rolling_friction epsd2`, sliding friction 0.5,
restitution 0.3, 1.0 s simulated.

## Result — strong, monotonic, settled

| μ_r | max pile height | r90 (radius holding 90% of particles) | mean KE/mass |
|---|---|---|---|
| 0.05 | 8.5 mm (≈ 1.7 particle Ø — almost flat) | 0.166 m (spread to the walls) | 1.3e-10 (settled) |
| 0.5 | 23.0 mm | 0.081 m | 1.3e-9 (settled) |

Higher rolling friction → visibly taller, narrower pile. Exactly the lever the angle-of-repose
calibration pulls.

## Syntax findings (corrects an assumption from planning)

- **epsd2 requires ONLY `coefficientRollingFriction`** — the epsd2 model *disables* the
  viscous damping torque (doc/gran_rolling_friction_epsd2.txt), so
  `coefficientRollingViscousDamping` is **not** needed. That knob belongs to `epsd` and
  `epsd3` (epsd3 additionally wants scalar `coeffRollingStiffness`). `cdt` needs only
  `coefficientRollingFriction`.
- Wall fixes must repeat the full model string including `rolling_friction epsd2` — done for
  all five primitive walls here; runs clean.
- `variable MUR index 0.3` + `-var MUR 0.05` override works as designed; `${TAG}` in the dump
  filename keeps per-run outputs separate — the pattern Phase 6's runner will rely on.

**OVITO check:** both series load headlessly (51 frames each); final frames show the flat
spread vs the conical pile.
