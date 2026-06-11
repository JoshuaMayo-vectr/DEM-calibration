# 05-movingMeshGran — Phase 1 run notes

**Date:** 2026-06-11 · **Command:** `mpirun -np 2 lmp_auto -in in.movingMeshGran -log log.movingMeshGran`
**Result:** ✅ normal completion, 10.7 s wall · 351 particle dumps + 351 STL mesh dumps.

**Modification vs original:** dump custom/vtk → dump custom; duplicate `type type` dropped.

## This is the `fix move/mesh` proof for the no-VTK build

Staging sequence (the exact skeleton Phase 3's settle-then-lift needs):

1. Insert 1500 spheres (r = 4 cm) over an inactive bucket mesh, settle to step 30 000.
2. **Activate** the mesh as a wall mid-run: `fix bucket_wall all wall/gran … mesh n_meshes 1 meshes cad1`.
3. **Linear translation** (= the lift mechanism): `fix movecad1 all move/mesh mesh cad1 linear -0.5 0. -0.3` — bucket scoops through the bed for 15 000 steps.
4. **`unfix movecad1` then a new `fix … move/mesh … rotate origin 0. 0. 0. axis 0. 1. 0. period 2.`** — bucket lifts the particles by rotating. Re-fixing a different motion on the same mesh works.

Verified from the STL dump frames (first vertex): (0.477, 0.000, 0.079) at step 30 000 →
(−0.150, 0.400, −0.110) after the linear stage → (0.213, 0.400, −0.029) mid-rotation.
Mesh moves; particles respond (1328 of 1500 still in the box at the end — some thrown out
of the open top by the rotating bucket, `thermo_modify lost ignore` absorbs them).

**Recorded for Phase 3:**
- `fix move/mesh` motion styles available (doc/fix_move_mesh.txt): `linear`,
  `linear/variable`, `wiggle`, `riggle`, `rotate`, `rotate/variable`, `viblin`, `vibrot`,
  plus superposition by stacking multiple move/mesh fixes on one mesh.
- Load-time STL transform: `move -50. -250. 0. scale 0.002 rotate … rotate …` (applied in
  argument order).
- A mesh can exist passively (for insertion staging) and be promoted to a granular wall
  later — useful if the Phase-3 cylinder should ignore particles during pre-fill.

**OVITO check:** series loads headlessly (351 frames); playback shows settle → scoop → lift.
