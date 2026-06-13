# Phase 15 — Particle shape (multisphere): plumbing + smoke test

**Status: ✅ qualified (plumbing shipped + smoke-verified end-to-end; calibration deferred).** 2026-06-13.

Same discipline as Phases 12–14: the *capability* ships (config-driven, own cache
namespace, byte-identical single-sphere default, smoke-verified on one real LIGGGHTS run);
the *calibration* is deferred to a shape-sensitive measured target, because wheat is matched
at the family level by single spheres and adding shape without a discriminating target would
only widen the equivalence family (the Phase-9 lesson). Scope is the **heap (`aor`) only**,
matching the Phase-14 geometry bounding — drum/drum45 carry no multisphere block and the 45°
hold-out is pinned single-sphere.

## What shipped

- **Template** ([templates/aor.in.j2](../../templates/aor.in.j2)): a `{% if multisphere %}`
  gate (Phase-13/14 `trim_blocks`/`lstrip_blocks` style) that (a) replaces the single-sphere
  PSD block with a `particletemplate/multisphere ... nspheres N ntry 1000000 spheres <inline
  x y z r ...> type 1` + a monodisperse `particledistribution/discrete`, (b) **swaps the
  integrator** `nve/sphere → multisphere` (multisphere *is* the rigid-body integrator —
  both present is a LIGGGHTS error), and (c) adds the `mol` body-id dump column (running
  dump + final `write_dump`). The cohesionless/single-sphere default render stays
  **byte-identical** to the static `aor.in` (the Phase-8.5 contract, now held a fourth time).
- **Runner** ([calibration/runner.py](../../calibration/runner.py)): `particle_shape` +
  `clump_spheres` join `material_canon` (validated), `_MAT_HASH_KEYS`, and `_WHEAT_CANON_CORE`
  at the `"sphere"`/`None` defaults — so a sphere material canonicalizes to `None` → byte-
  identical render → legacy cache preserved. New `_clump_block` (renders the inline
  particletemplate, parallel to `_psd_block`) and `_clump_equiv_volume` (deterministic
  Monte-Carlo union volume = the overlap-corrected body volume LIGGGHTS uses for mass).
  Multisphere heaps launch **serial (`-np 1`)** — the tutorial-proven path; single-sphere
  runs keep the validated 2-rank launch.
- **Measurement** ([calibration/measure.py](../../calibration/measure.py)): the angle fit is
  **unchanged** — the heap free surface *is* the sub-sphere top envelope, so `measure_angle`
  reads the clump heap straight from the sub-sphere cloud. `measure_bulk_density` gained a
  `clump_volume_m3` kwarg: when set (and the dump carries `mol`), it counts rigid **bodies**
  and weighs each by `ρ·V_clump` instead of summing sub-sphere volumes (which double-count
  intra-clump overlap and bias ρ high). Every single-sphere call runs the original path
  verbatim. Threaded runner → `render.render_trial` → `measure_heap` → `measure_bulk_density`.
- **Config** ([calibration/optimize.py](../../calibration/optimize.py)): `save_config`/`load_config`
  round-trip `particle_shape` + `clump_spheres` in the material block (written only for a
  multisphere clump — sphere stays omitted); **schema bumped v3 → v4** (v1–v3 load unchanged;
  a default-shape v4 is byte-identical to a v3). **Shape is NOT a searchable dimension** — it
  is a categorical model-form selector (like cohesion/normal_model/rolling_model), not a
  scalar knob; with no shape-sensitive target it would widen the family, so calibration is
  deferred (a future scalar aspect-ratio is the mechanical follow-up when such a target exists).
- **Schema** ([materials/schema.json](../../materials/schema.json)): an optional `clump` block
  under `contact_model` (`nspheres`, `spheres`, runner-recorded `equiv_radius_m`/`aspect_ratio`
  provenance). `materials/wheat.json` stays single-sphere, untouched (still schema-valid).
- **UI** ([calibration/ui.py](../../calibration/ui.py)): the clump geometry is config-authored
  (a research choice, not a UI knob), but the Configure tab **preserves** a loaded multisphere
  clump across a save and surfaces a read-only indicator — never silently drops it (the
  second-source-of-truth risk).
- **Tests**: new [tests/test_runner_phase15.py](../../tests/test_runner_phase15.py) (15 cases:
  default neutrality, pinned-hash survival, multisphere render, own namespace, drum45/drum
  single-sphere pin, clump validation, serial-ranks, clump-volume bounds + determinism),
  extended [tests/test_measure.py](../../tests/test_measure.py) (multisphere cone angle within
  ±0.5°, overlap-corrected bulk density + naive-over-read documentation, `mol` round-trip) and
  [tests/synth.py](../../tests/synth.py) (`make_multisphere_cone`, `make_packed_multisphere_cylinder`,
  `mol`-aware `write_dump`), plus the v4 config round-trip in test_optimize.py. **291 tests pass.**

## Smoke test (real LIGGGHTS, serial)

Representative prolate wheat clump (3 overlapping spheres, body axis = z, aspect ≈ 2.2):

| sub-sphere | x | y | z (m) | r (m) |
|---|---|---|---|---|
| cap | 0 | 0 | −0.0026 | 0.00175 |
| center | 0 | 0 | 0.0 | 0.00200 |
| cap | 0 | 0 | +0.0026 | 0.00175 |

| run | shape | AoR | ρ_bulk (slab) | n_bodies | namespace | wall |
|---|---|---|---|---|---|---|
| single-sphere wheat (cache) | sphere | **25.42°** (1 seed) | 753–834 | 4000 | `a3338ce730` | hit, 0 s |
| multisphere clump (smoke) | 3-sphere | **37.32°** (1 seed) | 734 | 1250 | `70190ea252` | 404 s, `-np 1` |

- **End-to-end pass.** LIGGGHTS accepted `particletemplate/multisphere` + `fix integr all
  multisphere` + the inline `spheres` list **on the first attempt**; inserted, simulated,
  rendered `snapshot.png` + `profile_fit.png`, measured AoR 37.32° (fit r² 0.954) and bulk
  density in its own cache namespace `70190ea252` — distinct from the wheat baseline
  `a3338ce730`, which **stays an instant cache hit** (the pinned-hash regression passes).
- **Shape is the model-form lever single spheres can't reach.** Same friction (fric 0.50 /
  μ_r 0.12 / e 0.50), single-sphere → 3-sphere clump: AoR **25.4° → 37.3° (+11.9°)** — the
  elongated, interlocking grain holds a far steeper heap than μ_r can extract from a sphere.
  This is exactly the residual the Phase-10 45° validation flagged (~−4° of model form at the
  true geometry) and the standing hint that shape may eventually be required (Checkpoint 5).
- **Clump-volume cross-check (0.09%).** Our deterministic `_clump_equiv_volume` = 7.139e-08 m³;
  LIGGGHTS' Monte-Carlo body mass 1.000327e-04 kg / ρ 1400 = 7.145e-08 m³ (r_equiv 2.574 mm,
  bounding-sphere r 4.35 mm). So the body-grouped bulk density weighs each clump by the same
  volume LIGGGHTS does.

## Gotchas (the plan's risks, as they actually played out)

- **`all_in yes` under-fills with clumps** (the flagged insertion risk): 1250 of the 3000
  requested clumps inserted (the bounding sphere is larger, so fewer fit the region) — it did
  **not** stall. The shallow bed then tripped `measure_bulk_density`'s own slab-vs-total
  backstop (`slab 734 vs total 648 > 12%`); the AoR still fit cleanly (r² 0.954). For a
  faithful multisphere heap, `n_particles` should be raised (and/or insertion relaxed to
  `volumefraction_region`) — but for a capability smoke test the heap formed and measured fine.
- **Serial cost.** 404 s for ~3750 sub-spheres on `-np 1` — within the planned ~2–4× single-
  sphere budget. A bigger or denser clump heap will want a higher wall limit.
- **`atom_style granular`** (ours) accepted `fix multisphere` with no change (the tutorial uses
  `sphere`); **`mol`** dumped correctly because `fix multisphere` sets `molecule_flag`.

## Deferred (the identifiability gate, generalized once more)

The exit criterion's "a shape-sensitive response is matched that the single-sphere model could
not reach" is **demonstrated** (37.3° is unreachable for a single sphere at this friction) but
not **calibrated** — there is no measured wheat shape target, and wheat is already family-
matched by spheres. The remaining work is mechanical when a shape-discriminating measurement
exists: pick/parametrize the clump (or expose a scalar aspect-ratio as a `SEARCHABLE_DIM` with
a `particle_shape == multisphere` guard, mirroring the cohed/rollvisc opt-ins), add the
shape-sensitive response + its noise floor, re-run the built optimizer, verify at 5 seeds.

**Engine ceiling** stands: LIGGGHTS-PUBLIC does multisphere clumps but **not** true polyhedra
and is CPU-only — if faceted shape or counts beyond CPU reach are first-order, the methodology
carries over but the engine changes (Aspirix / Rocky / EDEM); per the architecture note only
`templates/` + the dump parser change.
