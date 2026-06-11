# 03-cohesion — Phase 1 run notes

**Date:** 2026-06-11 · **Command:** `mpirun -np 2 lmp_auto -in <script> -log <log>`

| Script | Result | Wall time | Final state (1000 particles, r = 1.5 mm) |
|---|---|---|---|
| `in.noCohesion` | ✅ | 1.7 s | mean z = 2.3 mm, max z = 10.4 mm, ~3.8 neighbors/particle |
| `in.cohesion` | ✅ | 6.0 s | mean z = 6.6 mm, max z = 14.5 mm, ~7.7 neighbors/particle |

**Modification vs original:** dump custom/vtk → dump custom; duplicate `type type` column dropped.

## What the pair proves

The two scripts are **identical except two lines** — exactly the toggle Phase 3's template
needs if the Phase-2 material turns out cohesive:

```
pair_style gran model hertz tangential history cohesion sjkr
fix m6 all property/global cohesionEnergyDensity peratomtypepair 1 300000
```

(300 kJ/m³ is a strong setting — chosen by the tutorial to make the effect obvious.)

Effect is unmistakable in the numbers: with SJKR cohesion on, the settled bed is ~3× looser
(mean z 6.6 vs 2.3 mm) and the contact count doubles (clumping; particles also stick to the
cylinder wall instead of raining down). Cohesion also slows the run ~3× — more persistent
contacts to track. Worth remembering when budgeting Phase-3 runtimes if cohesion enters.

**Note:** the no-cohesion variant still defines `characteristicVelocity scalar 2.` — needed
only by Hooke; harmless but unnecessary under Hertz.

**OVITO check:** both series load headlessly (62 frames each); side-by-side final frames
show the dense settled bed vs the clumped cohesive bed.
