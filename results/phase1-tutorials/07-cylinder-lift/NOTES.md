# 07-cylinder-lift — the heap-test mechanism proof (Phase-1 exit criterion)

**Why this exists:** Phase 3's whole template hinges on one mechanism — fill an open-ended
mesh cylinder, settle, lift it with `fix move/mesh`, let the particles slump into a heap.
`05-movingMeshGran` proves move/mesh generically; this proves the exact cylinder mechanism,
with a **Python-generated STL** (the Phase-3 path) and the Phase-3 default contact model
(`hertz tangential history rolling_friction epsd2`, μ_s = 0.5, μ_r = 0.3, e = 0.3).

**Date:** 2026-06-11 · **Result:** ✅ normal completion, 23.5 s wall (2000 particles, 100k steps).

```
.venv/bin/python make_cylinder_stl.py                 # writes meshes/cylinder.stl
mpirun -np 2 lmp_auto -in in.cylinderLift -log log.cylinderLift
```

## Staging and measured outcome

| Stage | Steps | Evidence (from dumps) |
|---|---|---|
| 1. Fill + settle | 0–30k | 2000 spheres (r = 2.5 mm) confined to r ≤ 0.0475 m — inside the r = 0.05 m mesh, **no seam leaks** |
| 2. Lift at 0.1 m/s | 30k–80k | mesh bottom edge z: 0.0005 → 0.0505 m (exactly 5 cm); particles slump as the wall clears the bed |
| 3. Relax | 80k–100k | final state identical to step 80k — heap fully static |

**Final heap:** all 2000 particles retained (none tunneled through the mesh or got lost),
base radius 0.083 m, peak height 34 mm. Crude radial-profile flank fit:
**angle of repose ≈ 29°** — a plausible value for these frictions; Phase 4 owns the real
measurement.

**Timestep check** (`fix check/timestep/gran`, dt = 1e-5 s, E = 5e6 Pa, r = 2.5 mm):
Rayleigh fraction ≈ 0.03, Hertz fraction well under 0.1 — no warnings. The Phase-3
exit-criterion check passes on this configuration.

## De-risked for Phase 3

1. **Generated STL loads cleanly** into `fix mesh/surface` — 48-segment open tube, ASCII,
   outward normals, no end caps, no mesh-quality complaints from LIGGGHTS 3.8.
2. **Open-ended tube confines particles** — no leakage through facet seams at r_particle/
   r_cylinder = 0.05, even during the lift.
3. **0.1 m/s lift** is stable at dt = 1e-5; cylinder bottom edge starts 0.5 mm above the
   primitive floor plane (gap ≪ particle radius) to keep mesh facets off the wall plane.
4. `make_cylinder_stl.py` is already parameterized (`--radius --height --z0 --segments
   --out`) — reuse directly in Phase 3 at the lab geometry.

**OVITO check:** `post/cylLift_*.liggghts` (100 frames) + `post/cyl*.stl` mesh frames —
playback shows column → rising tube → conical slump.
