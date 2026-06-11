# 02-contactModels — Phase 1 run notes

**Date:** 2026-06-11 · **Command:** `mpirun -np 2 lmp_auto -in <script> -log <log>`

| Script | Result | Wall time | Dumps |
|---|---|---|---|
| `in.newModels` | ✅ normal completion | 7.6 s | 63 frames, 1800 particles |
| `in.oldModels` | ❌ `ERROR: Invalid pair style (../force.cpp:247)` | — | — |

**Modification vs original:** `dump custom/vtk … *.vtk` → `dump custom … *.liggghts` (no-VTK build).

## in.newModels — the modern syntax we standardize on

`pair_style gran model hertz tangential history` with knobs as `fix property/global`:
youngsModulus 5e6, poissonsRatio 0.45, coefficientRestitution 0.95, coefficientFriction 0.05.
1800 spheres (r = 2.5 mm, ρ = 2500) inserted at once via `fix insert/pack … insert_every once`
into a cylindrical region, settle under gravity inside primitive walls.

**Wall patterns recorded for Phase 3:**
- `fix … wall/gran model hertz tangential history primitive type 1 zplane 0.0` — static plane.
- `fix … wall/gran … primitive type 1 zcylinder 0.05 0. 0.` — **static** cylinder.
  Primitive walls cannot be moved by `fix move/mesh` (that needs a `fix mesh/surface` mesh
  wall), so the Phase-3 lift cylinder must be a mesh; primitives remain the right choice for
  the fixed base plate.
- Wall fixes must repeat the pair_style's full model string.

## in.oldModels — legacy stiffness syntax is NOT in this build

`pair_style gran/hertz/history 266000.0 NULL 500.0 NULL 0.5 1` (stiffness-style numeric
args) is rejected outright: **Invalid pair style**. So the legacy syntax is not merely
deprecated for us — it does not exist in this binary. Everything (and every doc page named
`*_stiffness`) that assumes it is out of scope. All templates use the
`gran model …` grammar exclusively.

**OVITO check:** newModels series loads headlessly (63 frames, radius column present);
playback shows insertion → free fall → settled bed.
