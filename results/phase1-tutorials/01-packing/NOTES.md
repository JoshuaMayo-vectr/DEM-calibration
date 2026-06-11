# 01-packing — Phase 1 run notes

**Status:** ran in Phase 0 (2026-06-11) as the build smoke test — not rerun. Dumps live in
`external/LIGGGHTS-PUBLIC/examples/LIGGGHTS/Tutorials_public/packing/post/` (203 files,
steps 1050–14700). The script here is the unmodified original: it already used plain
`dump custom`, which is why it ran on the no-VTK build without edits.

**Command (Phase 0):** `mpirun -np 2 lmp_auto -in in.packing` — 1×1×2 MPI grid.

**Contact model:** `pair_style gran model hertz tangential history`, no gravity,
particles inserted small and grown via `fix adapt` + `fix property/atom ... radius`.

**Knobs exercised** (`fix property/global`):
- `youngsModulus peratomtype 5.e6`
- `poissonsRatio peratomtype 0.45`
- `coefficientRestitution peratomtypepair 1 0.3`
- `coefficientFriction peratomtypepair 1 0.5`

**Why it matters downstream:**
- This file is the proven reference for the plain-text dump pattern used across Phase 1:
  `dump dmp all custom <N> post/<name>_*.liggghts id type x y z ix iy iz vx vy vz fx fy fz omegax omegay omegaz radius`
  (the original has a duplicated `type type` column — harmless; dropped in our other copies).
- The grow-in-place insertion trick is an alternative to pouring if Phase 3 fill ever
  needs densification.

**OVITO check:** series loads headlessly via the `ovito` pip package — 200 frames,
338 particles in the final frame, `Radius` property present. (Frame count is 200, not
203 — OVITO collapses duplicate-timestep files.) Desktop drag-and-drop of
`packing_*.liggghts` is the interactive equivalent.
