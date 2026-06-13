# Phase 9 — Second response: rotating drum (degenerate) → drawdown (discriminates)

The friction valley breaker. Phase 8 proved that a single AoR target leaves the
sliding-friction direction unconstrained (in-band sets span fric 0.25–0.60, the
optimum parked at the search edge). Phase 9 adds a **rotating drum** test —
dynamic angle of repose, target **36.17° ± 3.1°** (Sugirbay et al. 2022,
vertical drum, 5 rpm, 50 % fill) — and re-optimizes the weighted sum of both
σ-normalized errors so a single parameter set must match both responses.

## M0 — Protocol pinned (and a ground-truth correction)

Fetching the actual Sugirbay PDF exposed an **AI-extraction artifact in our
ground-truth doc**: the drum result was recorded as "24.3° ± 1.2°", a number
that appears nowhere in the paper. Verified values (their Tables 1–2): wheat
vertical-drum target **36.17°**, pooled within-group repeat spread
**σ ≈ 3.1°** (√MS_within = √9.73, 4 drum materials × 5 reps, material
insignificant at p = 0.68). Their calibrated set was also wrong in our doc:
actually μ_s = 0.15 / μ_r = 0.36 on a **7-sphere clump** model, with the
degeneracy valley explicitly acknowledged in the paper. The experiments doc
carries the full correction note + protocol table. This is exactly what the
M0 "pin the protocol before freezing geometry" gate exists to catch — σ_drum
is now a *measured* spread (unlike the assumed ±1.5° static σ).

## M1 — Drum template

| | |
|---|---|
| Template | [templates/drum.in](../../templates/drum.in), mesh generator [templates/make_drum_stl.py](../../templates/make_drum_stl.py) |
| Geometry | Ø150 mm (matched — preserves D/d ≈ 40) × **25 mm** axial (halved vs published 50 mm, budget) |
| End caps | static **frictionless primitive y-planes, atom type 3** (quasi-2D idealization; `CAPFRIC`/`CAPROLL` knobs expose the cap-sensitivity run) |
| Rotation | `fix move/mesh ... rotate axis 0 1 0 period 12` = 5 rpm (matched; Fr ≈ 2.1e-3, rolling regime confirmed visually) |
| Fill | 50 % of drum volume = **4600 spheres** at the locked PSD (streamed `insert_every` — single-shot insert/pack can't reach 37 % region solids) |
| Stages | settle 0.8 s → spin-up 2.2 s (discarded) → measure 3.2 s → **17 frames** every 0.2 s |
| Cost | **~8–9.5 min/run on 2 ranks** (~1.3e-7 s/particle-step — the flowing bed + rotating mesh cost ~2× the heap test). Documented deviation from the 2–5 min guideline; drum wall limit 1200 s |

Smoke triplet (fric/μ_r = 0.25/0.05, 0.40/0.12, 0.60/0.25) in
[smoke/](smoke/): dynamic AoR **25.9° → 30.7° → 35.2°** — monotone, visibly
different, continuous rolling (no slumping/centrifuging), timestep check clean
(Rayleigh 0.073, 0 dangerous builds), 4600/4600 inserted.

Two template gotchas caught by the first (discarded) smoke run:

- **`particles_in_region` over-inserts if the region under-covers the bed.**
  The insertion region must contain every physically reachable particle center
  (radial 0.0735 > R − r_min, |y| 0.011 > L/2 − r_min), otherwise settled
  wall-adjacent particles escape the count and the fix keeps topping up
  (first run: 6337 atoms instead of 4600).
- **`ceil()` on stage-step arithmetic turns FP noise into off-by-one step
  counts** (0.2/8e-6 → 25001): use `floor(x/dt + 0.5)`. The aor template
  happens to land exactly; the drum's frame bookkeeping would not have.

A 2.2 s spin-up was validated empirically before shortening it: windows
starting at step 375k drift < 0.6° (the steadiness guard fires at 1°).

## M2 — Measurement

New in [calibration/measure.py](../../calibration/measure.py):
`drum_surface_profile` (x-binned supported-max of particle tops),
`measure_drum_frame` (central-chord line fit + the Phase-4 shell refinement —
the binned extreme-value statistic carries the same ~0.8° bias on the drum
chord as it did on heap flanks), `measure_drum` (multi-frame mean + steadiness
guard + rotation-sign guard), `plot_drum_fit` (audit figure: representative
frame fit + angle-vs-time with the target band). CLI: `measure.py --drum
FRAME...`.

- **Accuracy**: single frames of the thin slice carry ±~1° realization noise
  (only ~40 surface bins vs the heap's full azimuth); the **17–19-frame mean
  is accurate to ≤ 0.12°** on synthetic beds — the ±0.5° Phase-4 bar applies
  there, and that is what the pipeline consumes. 14 new tests in
  [tests/test_measure_drum.py](../../tests/test_measure_drum.py) +
  `make_drum_bed`/`write_dump_series` generators in tests/synth.py.
- **Seed-noise floor (5 seeds at fric 0.40 / μ_r 0.12): 30.69° ± 0.27°** —
  vs σ_target 3.1°. The drum observable is *much* quieter than the static AoR
  (0.82°): time-averaging 17 frames beats a single relaxed-heap realization.
  Per-frame std ≈ 1.5°; one seed tripped the 1°-drift warning (+1.5° across
  the window) without moving the mean — guard is calibrated about right.

## M3 — Runner generalization

[calibration/runner.py](../../calibration/runner.py) gained a **response
registry** (`RESPONSES = {"aor": ..., "drum": ...}`): per-response template,
mesh, success key, cache prefix, wall limit, steady step. Key contracts:

- **Phase 7/8 cache stays byte-valid**: the "aor" canonical dict, hash, and
  `results/cache/<hash>/` layout are unchanged (pinned by regression test);
  drum trials live beside them as `results/cache/drum-<hash>/`. A live
  re-eval of the Phase-8 datum returned from cache in 0.24 s.
- Drum canonical adds protocol knobs to the hash: `rotper` (12.0), `capfric`/
  `caproll` (0.0) — the cap-sensitivity run gets its own cache entry.
- Drum pruning keeps final + all 17 steady frames (the multi-frame measurement
  stays reproducible from the pruned dir, ~12 MB/trial).
- **`evaluate_multi(params)`** flattens (response, seed) jobs into one pool —
  2×2 sims saturate jobs=4 in one wave — then finishes serially on the main
  thread (OVITO). One response failing leaves the other's value intact
  (per-response FAIL_PENALTY in the objective).
- [calibration/render.py](../../calibration/render.py): `render_drum_trial`
  with a fixed down-axis framing preset (the snapshot IS the measured
  cross-section); camera kwargs on `render_snapshot` (defaults unchanged).
- 16 new tests in [tests/test_runner_drum.py](../../tests/test_runner_drum.py)
  (stubbed engine; cache-compat pinning; evaluate_multi merge + failure
  isolation + single-response-cache reuse).

## M4 — Valley check (go/no-go) — **NO-GO on the first protocol variant**

9 in-band valley anchors (fric 0.248 → 0.600, the Phase-7/8 cached points),
drum response at 2 seeds each. Artifacts: [valley_check.csv](valley_check.csv),
[valley_check.png](valley_check.png),
[valley_contact_sheet.png](valley_contact_sheet.png),
[valley_verdict.json](valley_verdict.json).

**Result (frictionless-cap protocol): the drum does NOT discriminate.**

- Drum angle along the valley: **30.97–32.09°** — span 1.12° (< the 3° GO
  bar, barely above frame noise), Spearman vs fric **0.13** (no trend).
- The 36.17 ± 3.1° band is **unreachable on the valley**: 0 of 9 anchors
  in-band; the valley pins the drum at ≈ 31.5°, ~1.6° below the band floor.
- Interpretation: for single spheres, the slow-rolling drum angle and the
  static heap angle are governed by ~the same effective parameter
  combination — their iso-lines run parallel, so the second response adds
  no constraint. The drum IS friction-sensitive (smoke triplet spanned
  25.9–35.2°), just not *along* the iso-static-AoR direction.

**Cap-sensitivity side check (static frictional caps): unphysical.**
Setting CAPFRIC = FRICPW on the *static* primitive caps collapsed the angle
to 1.3°/2.3° — static frictional end walls grip the 6.8d-thin slice and hold
the bed while the shell slides underneath. Lesson: **a static cap is only
defensible frictionless; the published protocol's acrylic cover CO-ROTATES.**

**Second protocol variant: co-rotating frictional covers.** Diagnostic at
both valley ends with cover disks merged into the rotating mesh
(cap friction mirroring FRICPW): **+5.5° / +6.9°** lift — both ends into the
band. The cover drag is a first-order effect; the frictionless idealization
was the artifact. Protocol corrected properly: covers as a **separate
co-rotating mesh** (`make_drum_stl.py --caps-only`, atom type 3) with
friction **fixed at the published wheat–acrylic values 0.36 / 0.29**
(Sugirbay Table 11 — the real cover is always acrylic, regardless of where
the wheat–wheat search wanders; their values are clump-calibrated, carried
as a documented input). SPINUP 2.2 → 3.0 s (frictional cover holds a longer
transient); steady window = steps ≥ 475 k, 17 frames.

**Corrected-protocol valley re-check (9 anchors × 2 seeds):**
[valley_check.csv](valley_check.csv), [valley_check.png](valley_check.png),
[valley_verdict.json](valley_verdict.json); the frictionless-protocol run is
archived as `valley_check_frictionless.*`.

| | frictionless covers | co-rotating acrylic covers |
|---|---|---|
| drum range over the valley | 31.0–32.1° | **37.9–38.8°** |
| in 36.17 ± 3.1° band | 0 / 9 | **9 / 9** |
| span / Spearman vs fric | 1.12° / 0.13 | **0.92° / 0.43** |

**Verdict: NO-GO on valley collapse — but a qualified simultaneous match.**

1. **Target reachable** under the faithful protocol: every anchor lands in
   band (mean ≈ 38.3°, +0.7σ above center; the halved drum length
   over-weights cover drag and is the documented suspect for the offset).
2. **The drum does not discriminate along the valley** in either protocol
   variant: span < 1° ≪ 3° GO bar (and ≪ σ_drum). For single spheres with
   epsd2 rolling friction, the static heap angle and the slow-rolling drum
   angle are governed by the same effective bulk shear resistance — two
   tests in the same quasi-static/slow-flow regime cannot separate μ_s from
   μ_r. A discriminating second response must probe a different regime
   (e.g. orifice mass-flow rate, higher-Froude drum) or a different particle
   model (multisphere).
3. Consequence for the optimizer: the combined two-response loss is flat
   along the valley — the planned 40-trial study would localize nothing and
   was **not run** (the M4 gate doing precisely its job).
4. Checkpoint-4 reading: "a single parameter set matches both responses
   within their spreads" is satisfied — **by the entire valley family**, not
   a unique point. The ROADMAP's own fallback applies: *a family of
   parameter sets with stated equivalence is still a publishable, usable
   result.*

The equivalence family (both responses in band, 2-seed means):
fric 0.25 → 0.60 with rollfric 0.22 → 0.12 (anti-correlated), rest free —
i.e. the Phase-8 valley, now validated against a second (non-discriminating)
response. Representative set: the Phase-8 best (fric 0.60 / rollfric 0.120 /
rest 0.70) or the mid-valley point (fric 0.40 / rollfric 0.137).

## M5 — Two-response optimizer — PENDING

[calibration/optimize.py](../../calibration/optimize.py) now minimizes
`|AoR−27|/1.5 + |drum−36.17|/3.1` via `evaluate_multi`; **new study**
(`aor-drum-wheat-3d`, results/phase9-drum/study.db — the Phase-8 study is
frozen, its values are a different objective); fric widened to **(0.20, 0.80)**
(Phase-8 parked at 0.60); seeded from the 9 valley-check anchors (both
responses cached → instant); ~40 trials planned. New exit figure:
`valley_compare.png` (AoR-only vs combined loss over fric×rollfric — the
before/after of the degeneracy). 18 tests in
[tests/test_optimize.py](../../tests/test_optimize.py) incl. the two-surface
degeneracy-break stub (AoR-only minimum is a line; combined is a point).

*(NOT RUN — the M4 NO-GO made it moot: the combined loss is flat along the
valley, so there is nothing for the GP to localize. The module + tests stand
ready should a discriminating response be added.)*

## M6 — Checkpoint 4 (closure: equivalence family + drawdown probe)

Decision (user, 2026-06-12): close via the **documented equivalence family**,
preceded by one different-regime probe (drawdown) to test whether orifice
flow discriminates where the drum could not.

**5-seed verification of the representative family member**
(fric 0.4001 / rollfric 0.1374 / rest 0.5762 — mid-valley), both responses,
[family_verification.json](family_verification.json):

| response | 5-seed mean ± std | band | verdict |
|---|---|---|---|
| static AoR | **26.39° ± 0.63** | 27 ± 1.5° | ✅ in band (0.4σ) |
| drum dynamic AoR | **38.06° ± 0.20** | 36.17 ± 3.1° | ✅ in band (0.6σ) |
| bulk density (uncalibrated) | 781.7 kg/m³ | ≈ 780 lit. | ✅ |

The Checkpoint-4 simultaneous-match criterion holds at 5 seeds — for this
member and, per the M4 anchors (all 9 in both bands at 2 seeds), for the
family: **fric 0.25 → 0.60 with rollfric anti-correlated 0.22 → 0.12**
(rest unconstrained). The drum noise at 5 seeds (0.20°) confirms the M2
floor.

**Drawdown probe** ([drawdown-probe/](drawdown-probe/), template
[templates/drawdown.in](../../templates/drawdown.in), generator
[templates/make_annulus_stl.py](../../templates/make_annulus_stl.py)):
orifice discharge (D_o = 22 mm ≈ 5.9 d) from the aor cylinder over an
annular floor; plug opened mid-run by `fix move/mesh` (LIGGGHTS 3.8 allows
ONE wall/gran mesh fix, so the plug shares it and is moved, not unfixed);
flow rate from `fix massflow/mesh` (`delete_atoms yes` keeps the
shrink-wrapped domain bounded — the Phase-5 lesson) via an OLS slope on the
log's cumulative-mass series over the central 20–80 % mass window
(`measure.measure_drawdown`, 5 tests). Smoke: 47.1 g/s at r² 0.9994,
~140 s/run. Probe = 9 valley anchors × 2 seeds; verdict criterion is pure
discrimination (span ≥ 5× seed noise, monotone in fric) — no physical
target needed unless it passes.

**Probe verdict: DISCRIMINATES** —
[drawdown_probe.csv](drawdown-probe/drawdown_probe.csv),
[drawdown_probe.png](drawdown-probe/drawdown_probe.png),
[drawdown_verdict.json](drawdown-probe/drawdown_verdict.json):

| | |
|---|---|
| flow rate along the valley | **46.3 → 40.0 g/s**, monotone in fric (Spearman −0.90) |
| span vs seed noise | 6.8 g/s = **8.2×** the 0.84 g/s noise |
| steadiness | mass-vs-time r² > 0.998 on all 18 runs (no arching at D_o ≈ 5.9 d) |

Inertial orifice flow separates μ_s from μ_r where both slow-flow tests
(heap, drum) could not: higher sliding friction throttles discharge even
between valley members with identical heap and drum angles. **The
degeneracy is breakable — by the response the ROADMAP originally favored
for Phase 9.** What drawdown still lacks is a physical target: flow rate is
strongly geometry-bound and no wheat literature value exists for this
orifice, so a target must be sourced (literature discharge data
Beverloo-scaled to D_o = 22 mm, with stated uncertainty) before it can be
calibrated against rather than merely probed.

## Conclusion (Checkpoint 4)

1. **Simultaneous match: PASS (as a family).** Every static-AoR-matched set
   also matches the drum within its measured spread; the representative
   member is verified at 5 seeds on both responses (+ bulk density free).
   Checkpoint 4's fallback clause applies verbatim: a family of parameter
   sets with stated equivalence — fric 0.25 → 0.60, rollfric 0.22 → 0.12
   anti-correlated, rest unconstrained.
2. **Valley collapse: NOT achieved with the drum** — and shown to be
   unachievable by any slow-flow second response for this particle model
   (the two probes' iso-lines run parallel).
3. **The path to a unique point exists and is proven — but is target-bound.**
   Drawdown discriminates at 8× noise along the valley at ~140 s/run. The
   follow-up literature search
   ([experiments/drawdown-flowrate-literature.md](../../experiments/drawdown-flowrate-literature.md))
   found **no wheat-fitted Beverloo constants and no wheat data near our
   orifice scale**: the best model-based target is a soft 40 ± 12 g/s,
   wider than the family's whole 6.8 g/s span — a consistency check the
   family passes (all members in band, mild high-fric preference), not a
   calibration. **Phase 9 closes on the equivalence family.** A unique
   point becomes reachable with a *measured* flow rate (±2 g/s suffices;
   the drawdown rig is the cheapest of the three to build) — at which point
   the remaining work is mechanical: graduate drawdown to a third registry
   response and re-run the already-built multi-response optimizer.

## Lessons learned

- **Verify literature numbers against the source PDF before they become
  targets.** The drum target in our ground-truth doc (24.3° ± 1.2°) was an
  AI-extraction artifact; the real value is 36.17° (σ ≈ 3.1°). The M0
  protocol-pinning gate caught it before any compute was spent against the
  wrong number.
- **End-wall physics is first-order in thin rotating drums.** Frictionless
  covers under-read the dynamic angle by ~6°; a static frictional cap is
  not a sensitivity case but a different (wrong) experiment — it locks the
  bed. Co-rotating frictional covers (separate mesh, own friction pair,
  published wheat-acrylic values) are the faithful emulation.
- **A second response only helps if its iso-lines cross the first's.**
  Regime diversity, not test diversity, breaks degeneracy: heap + drum
  (both quasi-static/slow-flow) are redundant; heap + orifice flow
  (inertial) are not. Probe discrimination along the valley BEFORE
  committing to a response — 18 cheap sims killed a 5-hour optimization
  that could not have worked and found the one that can.
- **LIGGGHTS 3.8 allows exactly one wall/gran mesh fix** — multi-mesh walls
  must share it (`n_meshes N`), and anything that must appear/disappear
  mid-run (the drawdown plug) is moved out of the flow via fix move/mesh,
  not unfixed.
- **`particles_in_region` over-inserts when the region under-covers the
  bed** (wall-adjacent centers escape the count); cover every reachable
  center. And use `floor(x+0.5)`, never `ceil`, for stage-step arithmetic —
  FP noise turns ceil into off-by-one dump cadences.
- **The drum observable is 3× quieter than the heap** (seed σ 0.27° vs
  0.82°): time-averaging 17 flowing frames beats one relaxed-heap
  realization. Cheap variance reduction wherever a steady-state window
  exists.

## Cost

~3.5 h of simulation on the MacBook (10-core M-series, 2 ranks/sim,
jobs = 4): 3 + 3 smoke runs, 5-seed noise study, 2×18-sim valley checks,
2-anchor cap diagnostics, 10-sim family verification, 18-sim drawdown probe
+ 1 drawdown smoke ≈ 95 sims. No optimizer compute spent (correctly).

## Reproduce

```bash
# smoke triplet (manual, results/phase9-drum/smoke/)
mpirun -np 2 external/LIGGGHTS-PUBLIC/src/lmp_auto -in templates/drum.in \
    -var TAG med -var FRIC 0.40 -var ROLLFRIC 0.12 -var REST 0.5

# noise floor
.venv/bin/python calibration/runner.py eval --fric 0.40 --rollfric 0.12 \
    --response drum --seeds 5

# valley check (M4)
.venv/bin/python calibration/valley_check.py run --noise-floor 0.27

# optimization (M5)
.venv/bin/python calibration/optimize.py run --trials 40
.venv/bin/python calibration/optimize.py dashboard   # live UI
.venv/bin/python calibration/optimize.py plot        # figures + best.json
```

## Correction (2026-06-13, found during Phase 8.5)

`best.json` in this directory was a **test artifact, not evidence**, and has
been replaced with a tombstone. The M5 optimization above was cancelled at the
M4 gate (flat combined loss), so no study.db, figures, or best.json were ever
produced here — the file's content (best fric 0.617, n_trials 80, aor_std 0.4)
came from `tests/test_optimize.py`: `optimize.write_best` bound its default
output path at def time, so the suite's monkeypatched path was ignored and the
synthetic-surface stub result landed in the repo. The 0.617 "optimum" is the
stub surfaces' joint optimum. Fixed in Phase 8.5 (call-time path resolution +
regression and sentinel tests); the material card's evidence citation was
corrected in card v1.0.1. Real Phase-9 evidence: `family_verification.json`
and `valley_check.csv`.
