# Phase 13 — Cohesion model (SJKR): plumbing + smoke test

**Status: ✅ qualified (plumbing shipped + smoke-verified; calibration deferred).**
Date: 2026-06-13.

## What shipped

SJKR cohesion is now a config-selectable contact model and `cohed`
(cohesionEnergyDensity, J/m³) is an opt-in calibration dimension — following the
Phase-12 parameter-extension pattern, but with genuinely new template physics
behind a conditional that keeps the cohesionless default byte-identical.

- **Activation is material-gated.** A material with `cohesion: "sjkr"` renders the
  cohesive template variant; `cohesion: "none"` (the default) renders the existing
  cohesionless model. The flag joins the material's params-hash namespace.
- **`cohed`** is an opt-in searchable dimension (`optimize.SEARCHABLE_DIMS`), valid
  only when the study's material is cohesive (`load_config` rejects it otherwise).
  It enters the canonical params dict — and the hash — **only when > 0**, exactly
  like the material's default-omits-itself contract, so the cohesionless default is
  byte-identical to pre-Phase-13.
- **Templates.** `cohesion sjkr` is appended to the model string on the `pair_style`
  and every `wall/gran` fix, plus an `m6 cohesionEnergyDensity` fix
  (`peratomtypepair`, particle–particle (1,1) only — zero against walls). All three
  `.in.j2` variants (aor/drum/drum45). The hold-out `drum45` is forced cohesionless
  at both the canonical (`cohed` dropped) and render (`cohesive=False`) layers, so a
  cohesive `best.json` can never silently turn on SJKR for the validation.

### Files
- templates: `aor.in.j2`, `drum.in.j2`, `drum45.in.j2` (conditional SJKR block).
- `calibration/runner.py`: `RANGES["cohed"]`, `canonical()` (cohed>0 + drum45 drop),
  `material_canon()` (`cohesion` field + `_MAT_HASH_KEYS`/`_WHEAT_CANON_CORE`),
  `_render_text()` (`cohesive`/`cohstr` ctx + jinja `trim_blocks`/`lstrip_blocks`),
  `_build_argv()` (`-var COHED` when present), `_scaled_wall_limit()` (×3 for SJKR).
- `calibration/optimize.py`: `SEARCH_BOUNDS`/`SEARCHABLE_DIMS` cohed, `save_config`
  serializes `cohesion`, `load_config` rejects cohed without a cohesive material.
- `calibration/ui.py`: cohesive-material toggle + `cohed` opt-in bounds (disabled
  unless cohesive).
- `materials/schema.json`: optional `parameters.cohed`.
- tests: `test_runner.py`, `test_runner_material.py`, `test_optimize.py` (hash pins,
  cohesive namespace, byte-identical default render, cohesive render content, search
  dim + reject). Full suite: **249 passing**.

## Smoke test (real LIGGGHTS)

A cohesive demo material (wheat PSD/density/E, `cohesion: "sjkr"`) ran the `aor`
heap end-to-end:

| run | material | cohed | AoR | ρ_bulk | wall |
|---|---|---:|---:|---:|---:|
| cohesionless wheat (cache) | default | — | 25.42° (1 seed) | — | 0.0 s (cache hit) |
| **cohesive demo** | wet-demo | 12000 J/m³ | **28.19°** | 768 kg/m³ | 232 s |

- **SJKR launches, runs, renders, measures.** `cohed=12000` → AoR **+2.8° steeper**
  than the cohesionless twin (same PSD/density/E) — the physically correct direction
  (cohesion holds a steeper heap). `snapshot.png` + `profile_fit.png` produced.
- **Cache isolation holds.** The cohesive run is namespace `5182aa437c`; the
  cohesionless wheat candidate still hits the pinned legacy hash `a3338ce730`
  instantly — the Phase 7–10 cache is untouched.
- **Cost.** This `cohed` ran in ~232 s (~4 min, ~vertical-heap cost); the wall limit
  is scaled ×3 for SJKR as a safety margin (Phase-1's ~3× was for heavier cohesion).

## Gotcha (cost us the first smoke run)

**LIGGGHTS enforces contact-model keyword ORDER: `cohesion` must precede
`rolling_friction`.** Appending `... rolling_friction epsd2 cohesion sjkr` is
rejected — *"Unknown argument or wrong keyword order: 'cohesion'"*
(`pair_gran_base.h:129`). The parser walks a fixed sequence
(surface→normal→cohesion→tangential→rolling_friction, `contact_models.h`). The
verified `cohesion` tutorial puts it right after `tangential history`, so the
templates render `tangential history cohesion sjkr rolling_friction epsd2`. The knob
catalog (`docs/liggghts-knobs.md`) had the order backwards — **corrected**.

## Deferred (the demonstration, per the identifiability discipline)

The capability ships; the calibration does not — wheat is locked cohesionless and no
cohesion-sensitive measured target exists. Per the Phases-12–15 discipline, a
cohesion dimension without a discriminating physical target only widens the
equivalence family. When a cohesive material + a cohesion-sensitive bench measurement
exist, the remaining work is mechanical:

1. set a cohesive material card (`cohesion: "sjkr"`, measured PSD/density);
2. add a cohesion-sensitive response — a heap/funnel that won't stand without
   cohesion, or unconfined yield strength — to `runner.RESPONSES` (two precedents),
   with its own 5-seed noise floor (re-run the Phase-4 study for cohesive heaps:
   this is new, unvalidated physics);
3. name `cohed` in `search_bounds` (UI checkbox or config) and re-run the optimizer;
4. verify the calibrated set at 5 seeds.

Out of scope here: a cohesion-sensitive response/template, a real cohesive material
card + target, and a `drawdown.in.j2` cohesion variant.
