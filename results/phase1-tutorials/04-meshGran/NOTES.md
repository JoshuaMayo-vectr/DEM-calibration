# 04-meshGran — Phase 1 run notes

**Date:** 2026-06-11 · **Command:** `mpirun -np 2 lmp_auto -in in.meshGran -log log.meshGran`
**Result:** ✅ normal completion, 4.1 s wall · 134 particle dumps + 134 STL mesh dumps.

**Modification vs original:** dump custom/vtk → dump custom; duplicate `type type` dropped.
The `dump mesh/stl` line needs **no** VTK — kept as-is (this is how mesh motion is inspected
on our build).

## What it exercises

- **STL import as granular wall** — the Phase-3 cylinder mechanism's first half:
  ```
  fix cad all mesh/surface file meshes/mesh.stl type 1 scale 0.001 move 0. 0. 0. rotate axis 1. 0. 0. angle -90.
  fix granwalls all wall/gran model hooke tangential history mesh n_meshes 1 meshes cad
  ```
  `scale/move/rotate` happen at load time — handy for reusing one canonical STL at
  different sizes (Phase 3 will instead generate the cylinder at final size).
- **`fix insert/stream`** with a dedicated insertion-face STL — continuous pouring at a
  `particlerate`, vs `insert/pack`'s region fill. Only 500 of the nominal 10 000 particles
  enter before insertion stops at step 10 000 (rate 1000/s × 0.5 s) — tutorial as shipped.
- **`fix check/timestep/gran 1000 0.1 0.1`** with fractions in thermo — the Phase-3
  validation mechanism, seen working:
  `thermo_style custom step atoms ke c_1 f_ts[1] f_ts[2] vol`
  Final values: **f_ts[1] = 0.079 (Rayleigh), f_ts[2] = 0.043 (Hertz)** at dt = 5e-5 s,
  E = 5e6 Pa, r = 5 mm — comfortably under the 0.1 warning thresholds. LIGGGHTS prints a
  warning when a fraction exceeds its threshold; nothing fired here.
- Hooke model variant: requires `characteristicVelocity scalar 2.` — the extra arbitrary
  knob that argues for Hertz in our templates.

**OVITO check:** series loads headlessly (134 frames, 500 particles final); particles
stream in through the face and slide down the chute mesh.
