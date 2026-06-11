# Phase 5 — Visualization layer: validation batch + 20-run contact sheet

**Date:** 2026-06-11. **Deliverables:** [calibration/render.py](../../calibration/render.py)
(headless snapshot + per-trial hook + contact-sheet generator),
[contact_sheet.png](contact_sheet.png) (20 tiles, exit criterion), this batch
(7 new friction points + 1 deliberately broken run), tests in
[tests/test_render.py](../../tests/test_render.py).

## Rendering configuration (locked)

| Item | Value |
|---|---|
| Renderer | OVITO 3.15.4 pip package, **TachyonRenderer** (software ray tracer), `QT_QPA_PLATFORM=offscreen` — no GUI, no quirks on macOS arm64 |
| Import | `ovito.io.import_file()` auto-detects the LIGGGHTS custom dump — **no `columns=` mapping needed**; spheres sized from the `Radius` property automatically |
| Camera | **Fixed framing, never `zoom_all()`**: orthographic, `camera_dir=(2,1,-0.7)`, `camera_pos=(0,0,0.03)`, `fov=0.085` m — identical geometry across tiles is what makes a broken run pop out |
| Coloring | `ColorCodingModifier` on Radius, fixed scale 0.0017–0.0020 m (the locked PSD) so colors compare across trials |
| Snapshot | 800×600 PNG, white background, tag stamped top-left |
| Fallback | matplotlib 3D scatter with the same fixed limits, auto-engaged if OVITO import/render raises — a Phase-6 batch can never die because rendering broke |
| Contact sheet | PIL tiler, 400-px tiles + 26-px label strip (`<tag>  AoR <x>°`); missing/unreadable image → grey "MISSING" tile, never raises |

Per-trial render+measure cost ≈ 2 s — negligible next to the ~4 min simulation.

## Validation batch (8 runs, `run_batch.sh`)

Template knobs as locked in Phase 3 (R 0.040 / H 0.100 m, 4000 spheres,
E 1e7 Pa, dt 8e-6 s, lift 10 mm/s, REST 0.5, FRICPW=FRIC, ROLLFRICPW=ROLLFRIC).
Seeds are the 8M–15M-th primes — distinct from the template-internal seeds and
the Phase-4 seeds (3M–7M-th primes).

| tag | FRIC | ROLLFRIC | AoR [deg] | sector std | bulk rho [kg/m3] | wall [s] |
|---|---|---|---|---|---|---|
| f30r05 | 0.30 | 0.05 | 17.01 | 0.33 | 807 | 246 |
| f45r10 | 0.45 | 0.10 | 24.27 | 0.42 | 783 | 231 |
| f50r12 | 0.50 | 0.12 | 25.04 | 0.73 | 770 | 234 |
| f55r15 | 0.55 | 0.15 | 28.29 | 0.37 | 765 | 239 |
| f50r20 | 0.50 | 0.20 | 32.79 | 1.01 | 762 | 242 |
| f65r10 | 0.65 | 0.10 | 26.24 | 1.36 | 774 | 235 |
| f70r20 | 0.70 | 0.20 | 34.36 | 1.13 | 743 | 238 |
| broken_grav | 0.40 | 0.05 | n/a (all particles in flight) | — | — | ~60 |

Each good trial dir carries `snapshot.png`, `profile_fit.png`,
`measured.json` (the Phase-6 runner's output contract, written here by hand
to exercise the contact-sheet label path).

**Free Phase-7 observations:** the 27° ± 1.5° target is bracketed *within*
the screened range on multiple axes (f50r12 25.0° ↔ f55r15 28.3°), and bulk
density again lands around the 780 kg/m³ literature value with zero
calibration. The published friction ranges look sufficient — consistent with
the Phase-4 downgrade of the μ_r-ceiling worry.

## Exit criteria

1. **Both images, no GUI** ✓ — `render.py trial <dir>` produces
   `snapshot.png` + `profile_fit.png` headlessly (offscreen Qt; runs from a
   plain terminal with no display attached).
2. **20-run contact sheet with the broken run visually obvious** ✓ —
   [contact_sheet.png](contact_sheet.png): 12 existing trials (Phase 3 + 4)
   + 8 batch runs, 5×4 grid. The `broken_grav` tile is **blank white with
   "AoR n/a"** — all 4000 particles are tens of meters above the fixed
   camera frame. The relax-stage energy audit corroborates: KE = 11.3 J vs
   the < 2e-8 J static target.
3. **GRAVZ template edit behavior-neutral** ✓ — `variable GRAVZ index -1.0`
   defaults to the original gravity vector; f30r05 (FRIC 0.30) reads 17.0°,
   below med/lift10's 19.2° (FRIC 0.40) and consistent with the monotone
   friction response.

## Gotchas

- **`mpirun` eats stdin.** The first batch attempt drove the run list via
  `echo "$RUNS" | while read`; mpirun consumed the remaining lines and the
  loop exited after one run. Fix: `< /dev/null` on the mpirun command.
  The Phase-6 runner (Python `subprocess`) should pass `stdin=DEVNULL`.
- **Flipped gravity + `boundary m m m` (no ceiling) = unbounded flight.**
  The shrink-wrapped box grows with the particles; over the full 6.3 s sim
  they would climb ~170 m and the neighbor grid (0.002 m bins) would exhaust
  memory. The broken run therefore uses `LIFTH 0.005` (~1.3 s total). A
  *deliberately* broken run needs its blast radius contained.
- **`measure_heap` raises on the broken dump** (zero static particles →
  empty profile). `render_trial` intentionally propagates this — the
  optimizer must see the failure — while the `sheet` CLI catches it and
  labels the tile "AoR n/a".
- OVITO scene state is process-global: every render detaches its pipeline
  in a `finally` block, proven by the 20-dump single-process sheet run.

## Reproduce

```bash
bash results/phase5-contact-sheet/run_batch.sh   # 8 sims, ~30 min, skip-if-done
for d in results/phase5-contact-sheet/{f30r05,f45r10,f50r12,f55r15,f50r20,f65r10,f70r20}; do
  .venv/bin/python calibration/render.py trial "$d"
done
.venv/bin/python calibration/render.py sheet results/phase5-contact-sheet/contact_sheet.png \
  results/phase3-aor/{low,med,high,lift10,lift50,E5e7,smoke} \
  results/phase4-noise/seed_* \
  results/phase5-contact-sheet/{f30r05,f45r10,f50r12,f55r15,f50r20,f65r10,f70r20,broken_grav} \
  --ncols 5
.venv/bin/python -m pytest tests/ -q
```
