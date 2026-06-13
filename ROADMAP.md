# DEM Calibration Pipeline — Big-Picture Roadmap

## Progress at a glance

| # | Phase | Status |
|---:|---|:---:|
| 0  | Toolchain foundations (LIGGGHTS build, OVITO, Python env, repo scaffold) | ✅ |
| 1  | LIGGGHTS familiarization (tutorials, contact-model catalog, knobs & limits) | ✅ |
| 2  | Physical ground truth (material, PSD, densities, measured angle of repose) | ✅ (literature substitute) |
| ⚑  | **Checkpoint 1 — Stack viable & targets measurable** | ✅ (via literature substitute) |
| 3  | Parameterized angle-of-repose simulation template | ✅ |
| 4  | Automated measurement module (heap-angle fit, bulk density, noise floor) | ✅ |
| 5  | Visualization layer (OVITO interactive + headless snapshots + audit plots) | ✅ |
| ⚑  | **Checkpoint 2 — Simulation credible & objective trustworthy** | ✅ |
| 6  | Simulation driver (templating, parallel execution, result cache) | ✅ |
| 7  | Latin-hypercube screen & sensitivity analysis | ✅ |
| ⚑  | **Checkpoint 3 — Target reachable inside parameter ranges** | ✅ GO |
| 8  | Optimizer (Optuna Bayesian/TPE; pymoo NSGA-II if multi-objective) + dashboard | ✅ |
| 8.5 | Calibration UI (configure responses → start → watch live → results) | ✅ |
| 9  | Second response — drawdown/drum test breaks the friction degeneracy | ✅ (closed on the equivalence family: drum verified but degenerate with the heap; drawdown **discriminates 8× noise** but the literature target is too soft to exploit it — unique point awaits a measured flow rate, see open questions) |
| ⚑  | **Checkpoint 4 — Calibrated set matches reality within tolerance** | ✅ (qualified — family match, see checkpoint row) |
| 10 | Hold-out validation + material card deliverable | ✅ (qualified — 45°-drum hold-out **PASS at 1.8σ** of the pre-registered 2σ bar: the family predicts the never-calibrated response at measurement precision, but the response is family-degenerate and the quantified drum-length systematic (≈9.5°) exceeds the acceptance band, so this validates the *family*, not point accuracy; `materials/wheat.json` shipped, schema-valid, reproduces from cache) |
| 11 | Reproducibility & docs (pinned env, one-command rerun) | ⬜ |

Legend: ✅ complete · 🟡 in progress · ⬜ not started · ⏸ paused/blocked · ⚑ checkpoint

## Checkpoints

Checkpoints are **explicit go/no-go decision moments** between phases — not process gates between every phase. They exist because the plan makes technical and physical bets that we can only validate by running into reality. At each checkpoint we stop, evaluate against named criteria, and decide: continue / pivot / cut scope / stop.

| ⚑ | After phase | Question | If "no", what we do |
|---|---|---|---|
| **1** | Phase 2 | **Do we have a working simulation stack AND real measured targets with known spread?** LIGGGHTS runs reliably on this machine, the tutorials behave as documented, and we hold ≥ 5 repeats of a measured angle of repose (plus particle/bulk density) for the chosen material, with the repeat spread quantified. | Fix the toolchain (fall back to LIGGGHTS-INL or LAMMPS granular if 3.8.0 proves broken for our contact models) or simplify the measurement protocol — before writing any pipeline code. |
| **2** | Phase 5 | **Is the simulation credible and the objective trustworthy?** The simulated heap responds plausibly and monotonically to friction changes, the automated angle measurement agrees with manual measurement on rendered output to ±1°, and the seed-to-seed noise floor is below the measured physical spread. | Fix the physics/template or the measurement code. Do **not** start optimizing on an untrusted objective — every downstream phase inherits its errors. |
| **3** | Phase 7 | **Is the measured target inside the reachable response range, and do ≤ 4 parameters actually matter?** The LHS screen brackets the measured angle of repose, and sensitivity analysis identifies a small set of influential parameters. *(✅ GO 2026-06-12: 27 ± 1.5° bracketed in the interior, 7 in-band of 45; effective dimension 2 — rollfric ≫ fric ≫ rest. No model-form remedy needed.)* | Revisit the contact model (add cohesion, switch rolling-friction variant) or particle-scale assumptions (size scaling, shape via multisphere) before burning optimizer compute on an unreachable target. |
| **4** | Phase 9 | **Does the best parameter set match all calibrated responses within measurement spread?** Both the static heap response and the second (flow) response are matched simultaneously by a single parameter set. *(✅ qualified PASS 2026-06-12: the representative set fric 0.40 / μ_r 0.137 / e 0.58 matches heap 26.4 ± 0.6° (target 27 ± 1.5) AND drum 38.1 ± 0.2° (target 36.17 ± 3.1) at 5 seeds, bulk density 782 free — but so does the whole valley family (fric 0.25–0.60, μ_r anti-correlated): the drum proved degenerate with the heap (span < 1° along the valley, both cover protocols), so the fallback clause applies — the family is the documented result. The drawdown probe then showed orifice flow rate DOES discriminate (46.3 → 40.0 g/s along the valley, 8× seed noise, Spearman −0.9), but the follow-up literature search found no target tight enough to exploit it (best: soft 40 ± 12 g/s — wider than the family's span): the valley is breakable only by a measured flow rate. See results/phase9-drum/NOTES.md.)* | Add a response, widen parameter ranges, or accept a documented tolerance; only then proceed to validation. If the valley persists, report it honestly — a family of parameter sets with stated equivalence is still a publishable, usable result. |

## Context

Discrete Element Method (DEM) simulations are only as good as their contact-model parameters — and the parameters that govern bulk behaviour (**sliding friction, rolling friction, restitution, cohesion**) cannot be measured directly at the particle scale. The standard remedy is **bulk calibration**: measure cheap macroscopic responses of the real material (angle of repose, bulk density, flow rate), simulate the same tests, and search the parameter space until simulation matches physical reality.

The goal is a **calibration pipeline** over [LIGGGHTS](external/LIGGGHTS-PUBLIC/): a Python driver that templates LIGGGHTS input scripts, runs simulations in parallel, extracts bulk responses automatically, and hands the mismatch to an optimizer — so calibrated material parameter sets come out as versioned, evidenced artifacts rather than hand-tuned folklore.

**Decisions already locked:**

- **Engine: LIGGGHTS-PUBLIC 3.8.0**, built from source at `external/LIGGGHTS-PUBLIC/src/lmp_auto` (arm64 macOS, Open MPI, Boost, **no VTK** — Homebrew ships VTK 9.x, LIGGGHTS 3.8 supports only ≤ 8). Already compiled and smoke-tested on the bundled `packing` tutorial.
- **Output format: plain-text `dump custom`** files. OVITO reads them natively; the bundled `lpp` converter produces VTK for ParaView when needed. Nothing downstream depends on the VTK build.
- **Python driver layer** owns everything LIGGGHTS doesn't: templating, orchestration, post-processing, optimization. One venv in the repo; `numpy`/`pandas`/`matplotlib`, `jinja2`, `optuna` (and `pymoo` if multi-objective), `ovito` pip package for headless rendering.
- **Templated input scripts driven via `-var`** — the optimizer never edits files; it launches `lmp_auto -in templates/aor.in -var FRIC 0.5 -var ROLLFRIC 0.1 ...`.
- **Surrogate-assisted optimization first** (Optuna Bayesian/TPE), GA (pymoo NSGA-II) as the multi-objective option. A vanilla GA on raw simulations is ruled out by cost per evaluation.
- **OVITO is the primary visualizer**; ParaView held in reserve; matplotlib for all quantitative plots.
- **Calibration geometries stay small.** Each simulation is tuned to 2–5 minutes on this machine; that single number dictates the optimizer budget, parallelism, and total wall time.
- **Material: wheat grain** (dry, cohesionless — no SJKR), with **literature values as ground truth** since no physical sample is available; target AoR 27° ± 1.5° (σ assumed). *(locked at Phase 2/3, 2026-06-11)*
- **AoR test configuration** *(locked at Phase 3)*: lifted cylinder R 0.040 m / H 0.100 m, 4000 spheres at the fixed wheat PSD, E = 1e7 Pa / dt = 8e-6 s, **lift speed 10 mm/s** — the published protocol speed; a faster lift is not an option because the response proved strongly rate-sensitive (see Phase-3 lessons).

This document is the **big-picture roadmap**. Each phase below has a goal, exit criterion, dependencies, and risks. **Detailed per-phase implementation plans are drafted at the start of each phase**, not up front — so the plan stays adaptive.

## Design FAQ (locked answers)

**Q: Is the angle of repose an input parameter?**
**No — it is an output.** You measure it physically, simulate the same heap test, and tune the micro-parameters (sliding/rolling friction, restitution, cohesion) until the simulated angle matches the measured one. That inversion is the whole calibration problem.

**Q: How do parameters enter a simulation?**
As `fix property/global` lines in the input script, fed from command-line variables — so one template serves every candidate:

```
fix m4 all property/global coefficientFriction peratomtypepair 1 ${FRIC}
fix m5 all property/global coefficientRollingFriction peratomtypepair 1 ${ROLLFRIC}
fix m3 all property/global coefficientRestitution peratomtypepair 1 ${REST}
```

launched as `lmp_auto -in templates/aor.in -var FRIC 0.5 -var ROLLFRIC 0.1 -var REST 0.3`. Directly measurable properties (particle size distribution, particle density) are fixed inputs, never calibrated. Young's modulus is deliberately set 2–3 orders of magnitude below reality for timestep reasons — standard DEM practice, with negligible effect on quasi-static bulk behaviour.

**Q: Why not just run a genetic algorithm directly?**
Cost per evaluation. Each DEM run takes minutes; a vanilla GA wants thousands of evaluations — weeks of compute. Surrogate-assisted / Bayesian optimization typically converges in 50–200 evaluations, which is a day or two of wall time at 3 min/run. The GA earns its place in the multi-objective case (NSGA-II), seeded from the Phase-7 LHS data and ideally run *on the surrogate* (free), with only its proposed optima verified by real simulations.

**Q: How is non-uniqueness handled?**
Head-on — it is the central trap. Many (sliding friction, rolling friction) pairs produce the **same** angle of repose; a single target yields a valley of solutions, not a point. The fix is calibrating against **multiple independent responses simultaneously** (heap angle + bulk density + drawdown flow rate), which is why Phase 9 exists and why Checkpoint 4 demands a simultaneous match.

**Q: What about simulation stochasticity?**
Same parameters + different RNG seed → slightly different angle. The driver averages 2–3 seeds per candidate, and Phase 4 quantifies the noise floor explicitly. The target tolerance must exceed that floor, or the optimizer chases noise.

**Q: Why LIGGGHTS-PUBLIC when it's frozen at 3.8.0 (2018)?**
It is stable, free, widely used in published calibration work, and its input-script interface is ideal for external driving. The freeze is a known, accepted limitation: CPU/MPI only (fine at calibration scale, 10⁴–10⁵ particles), no upstream fixes. If it becomes limiting, the named fallbacks are **LIGGGHTS-INL** (maintained fork), **LAMMPS granular package** (same ancestry, actively developed, brew-installable), and **Yade** — and nothing about the pipeline architecture changes, only the template syntax.

## Visualization palette

Visualization is not a separate phase — each phase carries its own piece. Three distinct jobs, each mapped to a concrete tool. These are the cross-cutting design contract that Phases 1 / 4 / 5 / 8 / 8.5 all honour.

| Job | Tool | What it answers | Lands in |
|---|---|---|---|
| **Interactive 3D playback** | OVITO desktop (`brew install --cask ovito`) — reads `dump custom` natively, drag-and-drop, scrub the time series | "Does the simulation look physically sane?" | Phase 1 (manual) |
| **Profile-fit audit plot** | matplotlib — binned heap surface + fitted flank line + extracted angle annotated | "Is the objective function measuring what I think it measures?" | Phase 4 |
| **Per-trial headless snapshot** | `ovito` pip package — renders a PNG of the final heap for every trial, no GUI | "Can I skim 100 trials and spot the one where particles exploded?" | Phase 5 |
| **Optimizer dashboard** | optuna-dashboard — live web UI: objective vs. trial, parameter importance, contour plots | "Is it converging, and where's the friction valley?" | Phase 8 |
| **Calibration cockpit** | custom UI (`calibration/ui.py`, Streamlit-tier) — configure targets, start/stop runs, live trial gallery of snapshots + fits, results view | "Can I drive a calibration end-to-end without a terminal, and *see* every candidate heap as it lands?" | Phase 8.5 |
| **Report-grade figures** | matplotlib — convergence curve, measured-vs-simulated with error bars, sensitivity bars | "What goes in the write-up?" | Phases 7–10 |
| **Zero-dependency fallback** | LIGGGHTS' built-in `dump image` — crude PNG/PPM straight from the engine | "Quick look without opening any app" | available always |

## Phase detail

Each phase: **Goal · Exit criterion · Dependencies · Risks · Lessons learned** (placeholder).

---

### Phase 0 — Toolchain foundations

**Goal.** Everything installed and proven before any pipeline code. LIGGGHTS built from source; OVITO desktop installed; Python 3.11+ venv with the locked package set; repo scaffold created (`templates/`, `calibration/`, `experiments/`, `materials/`, `results/`, `external/`); initial commit pushed to the (currently empty) GitHub remote.

**Exit criterion.** `lmp_auto` runs a tutorial under MPI and writes dump files *(done — `packing` tutorial, 2 ranks)*; OVITO opens those dumps and plays the time series; `python -c "import optuna, jinja2, ovito"` succeeds inside the venv; `git push` shows the scaffold on GitHub.

**Dependencies.** Homebrew; Xcode command-line tools. *(Open MPI + Boost installed; LIGGGHTS 3.8.0 compiled — the remaining items are OVITO, the venv, and the scaffold.)*

**Risks.** The `ovito` pip package ships arm64 wheels only for recent Python versions — pin the venv Python to one with wheel coverage rather than building from source.

**Lessons learned.** Build with `USE_VTK = "OFF"` (Homebrew VTK 9.x is incompatible with LIGGGHTS 3.8); point `BOOST_INC_USR` at `/opt/homebrew/include`; Apple clang 21 compiles the 2018 codebase with warnings only. The `ovito` pip package (3.15.4) ships cp310–cp314 macOS arm64 wheels, so the venv runs on Homebrew Python 3.13 with no source build — the wheel-coverage risk did not materialize.

---

### Phase 1 — LIGGGHTS familiarization

**Goal.** Unpack what the engine can and cannot do before designing the template. Run the relevant bundled tutorials (`packing`, `cohesion`, `contactModels`, `meshGran`, `movingMeshGran`); catalog the contact-model space (Hertz/Hooke, `rolling_friction cdt/epsd/epsd2`, `cohesion sjkr/sjkr2`); document every calibration knob and its legal range in `docs/liggghts-knobs.md`; confirm `fix move/mesh` can lift a cylinder wall (the heap-test mechanism).

**Exit criterion.** A knob catalog exists covering all parameters we may calibrate, each with: LIGGGHTS syntax, physical meaning, literature-typical range, and which contact-model choice activates it. A throwaway script demonstrates a moving mesh wall working in our no-VTK build.

**Dependencies.** Phase 0 (binary).

**Risks.** Some tutorial scripts use `dump custom/vtk` and fail on our build — mechanical fix, swap to `dump custom` (already proven on `packing`).

**Lessons learned.** *(completed 2026-06-11 — runs in `results/phase1-tutorials/`, catalog in `docs/liggghts-knobs.md`)*

- The `dump custom/vtk → dump custom` swap was indeed mechanical (4 tutorials); `dump mesh/stl` needs no VTK and is how mesh motion is verified on this build.
- **Legacy stiffness pair styles are not compiled into this binary at all** (`gran/hertz/history …` → `Invalid pair style`) — the modern `gran model …` grammar is the only option, which is what we wanted anyway.
- **epsd2 needs only `coefficientRollingFriction`** — it disables the viscous rolling-damping torque; `coefficientRollingViscousDamping` belongs to epsd/epsd3. One fewer arbitrary constant: epsd2 confirmed as the Phase-3 default.
- Wall fixes must repeat the pair_style's full model string; primitive walls are static — anything that moves must be a `fix mesh/surface` mesh driven by `fix move/mesh`, and the unfix-then-refix staging (settle → lift) works mid-run.
- A Python-generated open-ended cylinder STL (48 segments, ASCII) loads cleanly and confines 2.5 mm particles with zero seam leakage through a 0.1 m/s lift; flank of the resulting heap fits ≈ 29° at μ_s = 0.5 / μ_r = 0.3. The generator (`make_cylinder_stl.py`) carries into Phase 3.
- The `-var` mechanism (defaults via `variable … index`, `${VAR}` in dump filenames to separate per-trial outputs) is proven — the Phase-6 runner pattern works.
- SJKR cohesion is a pure two-line toggle but costs ~3× runtime — remember when budgeting Phase-3 trials if the material is cohesive.

---

### Phase 2 — Physical ground truth

**Goal.** Measured reality to calibrate against. Choose the material (agri context — grain? affects whether cohesion enters the model). Measure directly: particle size distribution, particle density, poured bulk density. Measure the target response: static angle of repose via lifted-cylinder test, **≥ 5 repeats**, photographed against a contrast background, with the repeat spread computed. Record the protocol in `experiments/protocol.md` and the data in `experiments/`.

**Exit criterion.** `experiments/` contains raw photos, extracted angles, PSD and density numbers, and a stated target: *angle of repose = X° ± σ*. The σ is the calibration tolerance — nothing downstream can be more accurate than it.

**Dependencies.** None on code — this is lab work and runs in parallel with Phases 0–1.

**Risks.** Repeat spread too large (sloppy protocol → uncalibratable target) — mitigate with a consistent lift speed and fill procedure. Material too cohesive for a clean heap — switch test geometry or accept the cohesion parameter dimension early.

**Status — literature substitute (2026-06-11).** No physical sample was available, so this phase is satisfied by a **sourced literature stand-in** rather than lab measurement. Material chosen: **wheat grain** (dry, cohesionless). The synthetic ground truth lives in [experiments/ground-truth-wheat-literature.md](experiments/ground-truth-wheat-literature.md): equivalent sphere d = 3.8 mm (distribution 3.4–4.0 mm), particle density 1400 kg/m³, poured bulk density ≈ 780 kg/m³, **AoR target 27° ± 1.5°** (lifted-cylinder method, method-bound). The σ = 1.5° is **assumed, not measured** — it is the calibration tolerance and downstream accuracy ceiling. Checkpoint 1's "measured targets with known spread" is therefore met with literature values and an assumed spread; if a sample becomes available this is the file Phase 2 replaces.

→ **Checkpoint 1**: Stack viable & targets measurable? *(met via literature substitute — see above.)*

---

### Phase 3 — Parameterized angle-of-repose simulation

**Goal.** `templates/aor.in` — the single most important file in the repo. Cylinder region → `fix insert/pack` particles at measured PSD/density → settle → lift the cylinder via `fix move/mesh` at the lab lift speed → relax → `dump custom` final state. Every calibration parameter enters as a `-var` command-line variable; geometry and particle count tuned so one run takes **2–5 minutes**; timestep validated with `fix check/timestep/gran` against the Rayleigh criterion.

**Exit criterion.** Three runs at low/medium/high friction produce visibly different heaps in OVITO, slope steepening monotonically with friction; one run completes in ≤ 5 minutes; the timestep check passes at the softened Young's modulus.

**Dependencies.** Phase 1 (knob catalog, moving-mesh proof), Phase 2 (PSD, densities, lift speed).

**Risks.** Particle count vs. runtime tension — if the real PSD forces too many particles, apply documented particle upscaling (coarse-graining) and carry it as a stated assumption. Heap too small for a clean flank → widen the base plate, not the particle count.

**Lessons learned.** *(completed 2026-06-11 — template [templates/aor.in](templates/aor.in), runs + record in [results/phase3-aor/](results/phase3-aor/NOTES.md))*

- **Exit criterion met.** Triplet (FRIC/μ_r = 0.2/0.0, 0.4/0.05, 0.6/0.15) gives crude angles ≈ 0° / 18.4° / 26.1° — visibly different, monotonically steepening. Each run 2.75–3.9 min (≤ 5 min budget); Rayleigh fraction 0.073 at the softened E (timestep check clean, 0 dangerous builds); 4000/4000 particles retained.
- **Config locked:** cylinder R = 0.040 m / H = 0.100 m, 4000 spheres (~146 g), discrete PSD 3.4/3.7/4.0 mm, E = 1e7 Pa, dt = 8e-6 s, lift 10 mm/s. Two atom types (1 = particles, 2 = walls) so particle-wall friction can differ from particle-particle.
- **Young's modulus** confirmed AoR-insensitive (E 1e7 vs 5e7: Δ 0.6°) — kept at 1e7 because it doubles the timestep.
- **Lift speed is strongly rate-sensitive, NOT quasi-static** (18.4° @10 / 12.3° @25 / 10.4° @50 mm/s) — locked to the **10 mm/s published protocol** rather than a faster compromise, so the sim mirrors the physical test. This invalidated the plan's quasi-static assumption; the contingency (run at protocol speed) applied cleanly.
- **Checkpoint-3 preview:** the 27° target is reachable but only near the **high-μ_r corner** of the ranges; at published friction it is ~18°. Single spheres under-predict AoR and μ_r must absorb shape resistance. **Phase 7 should expect a high-μ_r optimum and may need to widen the μ_r ceiling > 0.15** (or accept multisphere).
- **Two gotchas for the Phase-6 runner:** (a) the `-var MESH` path **cannot contain spaces** — LIGGGHTS re-tokenizes it; pass a space-free relative path (repo root is `…/09 DEM-calibration`). (b) **All five RNG seeds must be distinct** (3 templates + distribution + insert) or LIGGGHTS aborts; only the insertion `SEED` is exposed as the noise lever.
- **Cost datum for the optimizer budget:** ~6.9e-8 s/particle-step on 2 ranks (788k steps × 4000 particles ≈ 230 s at 10 mm/s).

---

### Phase 4 — Automated measurement module

**Goal.** `calibration/measure.py` — the objective function's eyes, trusted blindly by the optimizer, therefore the most carefully tested code in the repo. Reads a final dump file; computes angle of repose by binning particle positions radially, extracting the surface profile, and fitting a line to the **flank** (not tip-to-toe — both ends are noisy); computes bulk density from the settled packing. Every call emits the profile-fit audit plot. Quantify the seed noise floor: same parameters, 5 seeds, report the angle spread.

**Exit criterion.** Unit tests pass on synthetic heaps of known angle (±0.5°); automated angle agrees with manual on-screen measurement of rendered output to ±1°; the seed noise floor is documented and is **below** the physical spread σ from Phase 2 *(= the assumed σ of 1.5° from the literature substitute)*.

**Dependencies.** Phase 3 (dump files to measure — final-state dumps exist under `results/phase3-aor/*/post/`, and the throwaway `results/phase3-aor/crude_angle.py` flank fit is the naive baseline this module replaces; note it under-reads by including the rounded toe).

**Risks.** This is the highest-leverage failure point in the project — a silently wrong angle fit poisons every optimizer trial. Hence the audit plot on every call and the synthetic-heap tests. Seed noise exceeding physical σ → average more seeds per candidate or enlarge the heap.

**Lessons learned.** *(completed 2026-06-11 — module [calibration/measure.py](calibration/measure.py), tests in `tests/`, noise study + run record in [results/phase4-noise/](results/phase4-noise/NOTES.md))*

- **All three exit criteria met:** 13 synthetic/regression tests green (cones 15/25/30° within ±0.5°); manual grid readout vs automated angle agrees to 0.2° (med) / 0.8° (high); **seed noise floor σ = 0.82° < 1.5° physical σ** (5 seeds at the high set, mean 29.40°, range 1.96°).
- **Binned profile fits carry an extreme-value bias** (~0.8° on synthetic cones): per-bin max-statistics sit closer to the true surface where bins are populous, tilting the fit. Fixed with a two-stage fit — binned fit for the initial line, then OLS over all particle tops within ±0.75 diameter of it (constant-thickness shell → bias becomes a constant offset that cancels in slope). Sector fits reuse the pooled line; standalone quadrant fits are too sparse to trust.
- Accuracy on volume-matched synthetic cones (12–30°, 10 seeds each): mean |error| ≈ 0.26°, worst 0.6° — well under the 1.5° target tolerance.
- **The toe-free fit reads above crude on every Phase-3 dump**, as predicted: med 18.4° → 19.2°, high 26.1° → **29.4° (5-seed mean)**. The 27° target is now *bracketed inside* the med–high range instead of sitting at its corner — the Phase-3 "high-μ_r corner" worry has relaxed (see open questions).
- Bulk density from the settle-end frame (interior-slab estimator): 753–834 kg/m³ across all runs vs literature ≈ 780 — the fixed PSD/particle-density inputs land the packing right with zero calibration; seed noise on density is negligible (±4 kg/m³).
- **Optimizer guidance for Phases 6–8:** average 2 seeds per candidate (σ/√2 ≈ 0.6°); per-run wall time at the high set confirmed 3.8–4.0 min on 2 ranks.

---

### Phase 5 — Visualization layer

**Goal.** Wire up the remaining rows of the visualization palette. Headless per-trial rendering via the `ovito` pip package — every future trial directory gets `snapshot.png` + `profile_fit.png` automatically; a contact-sheet generator tiles N trials into one image for minute-scale skimming of an overnight batch.

**Exit criterion.** Running the Phase-3 template through the driver-to-be's rendering hook produces both images with no GUI; a 20-run contact sheet renders and the one deliberately broken run (gravity flipped) is visually obvious in it.

**Dependencies.** Phase 4 (profile fit to plot), Phase 0 (ovito package).

**Risks.** Headless OVITO rendering on macOS occasionally needs an offscreen-context workaround — budget a half-day, fall back to `dump image` PPMs if it fights back.

**Lessons learned.** *(completed 2026-06-11 — module [calibration/render.py](calibration/render.py), batch + 20-run sheet + run record in [results/phase5-contact-sheet/](results/phase5-contact-sheet/NOTES.md), tests in `tests/test_render.py`)*

- **The macOS offscreen risk did not materialize.** `QT_QPA_PLATFORM=offscreen` + OVITO's TachyonRenderer (software ray tracer) rendered headlessly on the first attempt; the budgeted half-day was not needed. Renderer choice is isolated in one factory (Tachyon → OSPRay → OpenGL) and a matplotlib-3D-scatter fallback auto-engages if OVITO ever fails, so a Phase-6 batch can't die because rendering broke.
- `ovito.io.import_file()` reads our `dump custom` files with **no column mapping** — format auto-detected, sphere radii picked up from the dump.
- **Fixed camera framing (never `zoom_all`) is the design load-bearer**: every tile shares one orthographic view and one radius color scale, so the gravity-flipped run renders as a blank tile labeled "AoR n/a" — instantly spottable among 19 heaps in [contact_sheet.png](results/phase5-contact-sheet/contact_sheet.png).
- `templates/aor.in` gained a `GRAVZ` fault-injection variable (default −1.0 preserves behavior exactly; regression-checked). A flipped-gravity run must be kept **short** (`LIFTH 0.005`): with no ceiling and shrink-wrapped boundaries, the full-length sim would send particles ~170 m up and exhaust neighbor-grid memory.
- **`mpirun` eats stdin** — a `while read` loop driving the batch lost all runs after the first until `< /dev/null` was added. The Phase-6 runner must use `stdin=DEVNULL` on every launch.
- The 7 new friction points double as free Phase-7 training data: AoR 17.0–34.4° brackets the 27° target *between* interior points (25.0° @ 0.50/0.12 ↔ 28.3° @ 0.55/0.15), and bulk density stays around the 780 kg/m³ literature value uncalibrated.
- Per-trial render+measure cost ≈ 2 s — negligible against the ~4 min simulation; `render_trial(trial_dir)` is the ready-made Phase-6 hook (returns the measure dict + snapshot path; trial dirs carry `snapshot.png`, `profile_fit.png`, `measured.json`).

→ **Checkpoint 2**: Simulation credible & objective trustworthy? — **✅ GO (2026-06-11).**
- *Plausible, monotone friction response:* low → med → high = ~0° → 19.2° → 29.4°, and the Phase-5 batch fills the interior monotonically (17.0° → 24.3° → 25.0° → 28.3° with rising μ_s/μ_r); the 27° target is bracketed inside the screened range.
- *Automated vs manual angle ±1°:* met in Phase 4 (0.2° med / 0.8° high on the gridded side-view readout).
- *Seed noise floor below physical spread:* met in Phase 4 (σ = 0.82° < 1.5° assumed physical σ).
- *Audit tooling in place:* every trial now emits a profile-fit plot and a fixed-frame snapshot, and a broken run is visually obvious in the contact sheet — the objective cannot silently rot. **Proceed to Phase 6.**

---

### Phase 6 — Simulation driver

**Goal.** `calibration/runner.py` — parameter dict in, observables out. Renders the jinja2 template (or passes `-var` flags directly), launches `lmp_auto` under MPI, runs 3–4 candidates in parallel (2 ranks each, within the machine's core budget), averages over seeds, invokes `measure.py`, and **caches every result to disk keyed by a params hash** — optimizers revisit old points and simulations are too expensive to repeat. Every trial directory is self-contained: rendered input, log, dumps, snapshots, measured values as JSON.

**Exit criterion.** `runner.evaluate({"fric": 0.5, "rollfric": 0.1, ...})` returns `{"aor": ..., "bulk_density": ...}`; a repeated call returns instantly from cache; 4 candidates run concurrently without oversubscribing the machine; killing and rerunning a batch resumes from cache.

**Dependencies.** Phases 3–5.

**Risks.** Zombie MPI processes on candidate timeout — enforce hard wall-time limits and process-group kills from day one.

**Lessons learned.** *(completed 2026-06-11 — module [calibration/runner.py](calibration/runner.py), tests in `tests/test_runner.py`, run record in [results/phase6-driver/NOTES.md](results/phase6-driver/NOTES.md))*

- **All exit criteria met.** `evaluate({"fric":0.5,"rollfric":0.12})` → aor 25.86° / ρ 778 (2-seed mean, matches the Phase-5 f50r12 ≈ 25° datum); a repeat call returns in **0.64 s** from cache (vs 4:14 live); `evaluate_batch` runs candidates concurrently (auto `jobs`=4 on the 10-core box, ~4 ranks busy) and resumes completed trials from cache; a fault-injected `gravz=1.0` candidate returns `aor=None` without crashing the batch and leaves no orphan `lmp_auto`.
- **OVITO is not thread-safe.** Rendering inside the thread pool segfaults off the main thread (Qt/OVITO state is process-global — the Phase-5 note foreshadowed it). The runner splits each job into `_simulate` (cache-check + `mpirun`, parallelized) and `_finish` (render+measure+prune+JSON, **main thread, serial**). Post-processing is ~2 s/trial — free against ~4 min sims.
- **Cache = canonical-params hash; seed is a separate dimension.** Params are rounded to 4 dp before hashing so an optimizer's near-duplicate floats (`0.50000001` vs `0.5`) collide. A recorded failure is *not* a cache hit (only `measured.json` with an `aor_deg` is), so transient timeouts self-heal on resume while good trials are skipped; a stale partial dir is wiped before relaunch.
- **Each trial is self-contained then pruned** to the final + settle dumps only (the ~142 intermediates deleted) — compact enough to keep an overnight batch on disk. `results/cache/` is git-ignored.
- All Phase-3/5 gotchas held in code: space-free relative `MESH`, `stdin=DEVNULL`, only `SEED` varied, `start_new_session` + `os.killpg` on timeout.

---

### Phase 7 — Latin-hypercube screen & sensitivity analysis

**Goal.** ~50–100 runs overnight over literature-informed ranges (sliding friction 0.1–1.0, rolling friction 0.0–0.5, restitution 0.1–0.9, cohesion 0 unless Phase 2 demanded it). Deliverables: sensitivity ranking (which parameters move the angle — restitution usually barely matters for static heaps; **freeze the insensitive ones**), confirmation the measured target lies inside the reachable response range, and a free training set for the surrogate.

**Exit criterion.** Sensitivity bar chart + response scatter exist in `results/lhs-screen/`; the measured angle ± σ is bracketed by the screened responses; the calibration dimension is cut to the parameters that matter (expect ≤ 4).

**Dependencies.** Phase 6.

**Risks.** Target outside the reachable range — that is precisely what Checkpoint 3 exists to catch before optimizer compute is spent.

**Lessons learned.** *(completed 2026-06-12 — module [calibration/screen.py](calibration/screen.py), tests in `tests/test_screen.py`, results + run record in [results/phase7-lhs/NOTES.md](results/phase7-lhs/NOTES.md))*

- **Exit criteria met on 45 candidates × 2 seeds = 90 runs** (within the 50–100 budget). AoR spans **0.0–35.0°**; 27 ± 1.5° is bracketed in the interior (7 in-band), not clipped at an edge. The screen was planned at 60 candidates but the last 15 were skipped — an overnight run was power-cut after 90/120 sims finished, those were salvaged by re-measuring their dumps, and the gate conclusions were already robust.
- **Rolling friction is the dominant lever; sliding friction secondary; restitution negligible** — δ/S1/ρ = rollfric 0.53/0.70/+0.91 ≫ fric 0.16/0.11/+0.28 ≫ rest 0.02/0.07/+0.19. Effective calibration dimension is **2**. rest is practically freezable for Phase 8.
- **A single sphere needs substantial μ_r to reach 27°:** monotone by bin (μ_r 0–0.05 → 9.9° … 0.20–0.25 → 31.9°), and at μ_r < 0.05 even high sliding friction tops out at ~17–19°. The Phase-3 μ_r-ceiling worry is resolved by the widened 0.25 range; **multisphere is not needed.**
- **The friction valley is real and quantified** — in-band candidates span fric 0.25→0.59 at rollfric 0.12→0.25. A single AoR target gives a valley, not a point: the empirical case for Phase 9's second response.
- **Objective trustworthy:** seed noise aor_std median 0.37° < 1.5° tolerance; uncalibrated bulk density 753–827 kg/m³ straddles the literature ~780.
- **Salvage pattern for the driver:** an interrupted batch leaves finished sims unmeasured (measure runs at `_finish`, not per-sim); re-running `runner._finish` over the existing `*_final.liggghts` dumps banks them as cache hits without re-simulating. A plain resume would have wiped and re-run them.

→ **Checkpoint 3**: Target reachable inside parameter ranges? — **✅ GO (2026-06-12).** Target bracketed in the interior; effective dimension 2 (rollfric ≫ fric ≫ rest); no model-form remedy (cohesion / rolling-variant / multisphere) needed. **Proceed to Phase 8**, seeded from the LHS results — expect a rollfric-led optimum with fric loosely constrained (the valley Phase 9 then breaks).

---

### Phase 8 — Optimizer

**Goal.** `calibration/optimize.py`. Objective: weighted sum of normalized errors, each term scaled by its measurement uncertainty from Phase 2 — e.g. `w₁·|AoR_sim − AoR_meas|/σ_AoR + w₂·|ρ_sim − ρ_meas|/σ_ρ`. Engine: **Optuna** (TPE/GP sampler), trials persisted to SQLite so runs survive kills and resume; optuna-dashboard live during the run; LHS results enqueued as seed trials. If Phase 9 goes multi-objective: **pymoo NSGA-II**, population ~20, seeded from the same data. Optional hybrid at zero extra cost: fit a Gaussian-process surrogate on all cached runs, run the GA on the surrogate, verify only its proposed optima with real simulations.

**Exit criterion.** An overnight run (50–150 trials) converges to a parameter set matching the heap angle within σ; the study resumes cleanly after a mid-run kill; the dashboard shows the expected sliding-vs-rolling-friction valley in the contour plot.

**Dependencies.** Phase 7 (ranges, seeds, frozen parameters).

**Risks.** Converging into the degeneracy valley is *expected*, not failure — it is the signal to proceed to Phase 9. Optimizer chasing seed noise → re-check the Phase-4 noise floor against the convergence plateau.

**Lessons learned.** *(completed 2026-06-12 — module [calibration/optimize.py](calibration/optimize.py), tests in `tests/test_optimize.py`, study + figures + run record in [results/phase8-optimizer/](results/phase8-optimizer/NOTES.md))*

- **All exit criteria met on 56 trials** (35 LHS seeds + 21 GP; stopped early on convergence — within the 50–150 budget). Best: **AoR 26.95° (loss 0.036σ) at fric 0.60 / rollfric 0.120 / rest 0.70**; a deliberate mid-run SIGKILL lost only the in-flight trial and `resume` re-attached cleanly; the contour shows the predicted anti-correlated fric↔rollfric valley.
- **Sampler choice deviated from the plan's TPE-default**: GPSampler (user choice) — it pulls in `torch`, and fANOVA importances need `scikit-learn`; both pinned. GP exploitation was strikingly efficient: **17 of 21 proposals in-band** vs 7/45 for the LHS — warm-starting from screened data beats extra trials by a wide margin.
- **Convergence took 4 GP trials** after the 35-seed warm start; the rest mapped the valley floor. ~20 GP trials is the right budget at effective dimension 2, not 40+.
- **The σ-normalized loss made "don't chase noise" operational**: best loss 0.036 sits far below the ≈0.25 seed-noise floor, and 9 trials tie at/below it — the plateau is noise-bound, exactly the predicted risk, handled by stopping rather than refining.
- **The fric direction is unconstrained by a single AoR target** — the optimum parked at the fric = 0.6 search-bound edge and the in-band set spans fric 0.25–0.60 at rollfric 0.25–0.11. Cleanest empirical case yet for Phase 9; consider widening fric > 0.6 there.
- **Single 2-seed trials can look in-band by luck** (one valley trial: aor_std 1.87° > σ) — verify the final calibrated set with more seeds before Checkpoint 4.
- **Visualization landed beyond the palette row**: live optuna-dashboard on the SQLite study during the run, plus an animated plotly 3-D search view (`search3d.html`) scrubbing the trial sequence through (fric, rollfric, rest) space.
- **enqueue_trial + the Phase-6 cache is the right seeding pattern** — the whole 35-point warm start cost 0.8 s and keeps every DB row schema-uniform; the LHS rows outside the search box (rollfric < 0.05, unreachable per Phase 7) are skipped on physical grounds.

---

### Phase 8.5 — Calibration UI

**Goal.** `calibration/ui.py` — a domain-specific configure → start → watch → results cockpit, replacing the generic optuna-dashboard view for day-to-day use. Strictly a **thin read layer + launcher**: it owns no calibration logic and invents no state. Select the responses to calibrate (checkboxes mapping one-to-one onto the Phase-9 response registry), set target ± σ, weights, and search bounds; the UI writes a `config.json` **that the CLI also accepts** — the file, not the browser session, is the source of truth. Start spawns `optimize.py run` as a subprocess; Stop kills it, safe under the study's resume semantics. Live view: convergence curve against the seed-noise floor, the fric–rollfric contour filling in, and a trial gallery streaming each candidate's `snapshot.png` + `profile_fit.png` as it lands (the Phase-5/6 artifacts, finally surfaced). On completion: `best.json` rendered as a material-card preview. Polling the SQLite study + trial dirs every few seconds suffices — trials complete every ~4 min. Built at the **Streamlit/NiceGUI tier**; a FastAPI + React rebuild is justified only if this becomes a product others use.

**Exit criterion.** A study configured entirely in the UI (responses, targets, σ, bounds) runs from the Start button and updates live with no terminal involved; Stop mid-run leaves a study that `optimize.py resume` continues cleanly; replaying the UI-written `config.json` through the bare CLI reproduces the identical study; every finished trial's snapshot and profile fit appear in the gallery within one poll interval.

**Dependencies.** Phase 8 (study schema, `optimize.py` CLI verbs, `best.json`); Phases 5–6 (per-trial images, self-contained cache layout). Designed *against* the Phase-9 response registry — the response checkbox list and the runner's registry are the same data structure, so this builds alongside Phase 9, not before it.

**Risks.** Becoming a second source of truth — every knob must round-trip through `config.json` or Phase 11's one-command replay dies; enforce by making the CLI path the tested one. Scope creep: the UI advances no checkpoint, so it is timeboxed and optuna-dashboard stays wired as the always-working fallback. Concurrent SQLite access is read-only from the UI (all writes stay in the run subprocess) — the same pattern optuna-dashboard already proves safe.

**Lessons learned.** *(completed 2026-06-12 — UI [calibration/ui.py](calibration/ui.py) (Streamlit, `streamlit run calibration/ui.py`), process/read layer [calibration/ui_state.py](calibration/ui_state.py), config plumbing in [calibration/optimize.py](calibration/optimize.py), tests in `tests/test_ui_state.py` + extended `tests/test_optimize.py`; demo study `results/studies/ui-demo/`)*

- **All four exit criteria verified.** A study configured from defaults ran from Start with no terminal (9 valley-anchor trials, all cache hits, < 30 s); Stop mid-flight left 9 COMPLETE + 1 stale RUNNING row and `optimize.py resume --config` continued cleanly with a live GP trial; deleting only `study.db` and replaying the UI-written config through the bare CLI reproduced the identical study (same name, same top-5 params/losses/order); the gallery resolved 42/42 items with both images — cache hits appear within one poll by construction.
- **Streamlit chosen over NiceGUI** (per-study dirs `results/studies/<name>/`). Its script-rerun model forced the right architecture: zero run state in the browser session — every render re-derives from pidfile + SQLite + trial dirs, so a page reload mid-run costs nothing. `st.fragment(run_every=…)` polls status/gallery at 5 s and the matplotlib figures at 15 s.
- **The registry IS the UI** as designed: each `runner.RESPONSES` entry gained a `"calib"` block (label, result/std keys, fit-PNG name, target ± σ, noise floor, weight, holdout flag) — the checkbox list, the generic objective, and the gallery all read it, so adding drawdown to the registry will surface it in the UI with zero UI changes. `drum45` carries `holdout: True`: rendered disabled, rejected by config validation — calibrating against the hold-out is structurally impossible, not just discouraged.
- **The config refactor fixed a real latent bug**: `optimize.py` bound path defaults at def time (`write_best(path=BEST_JSON)`), so the test suite's monkeypatch was ineffective and `results/phase9-drum/best.json` had been silently overwritten with a test artifact (stub values `aor_std 0.4`, `n_trials 80`). All paths now resolve at call time through `default_config()`; a regression test pins the fix and a sentinel test guards the phase9 artifacts. **Resolved (2026-06-13):** the contaminated file was replaced with a tombstone (the cancelled M5 study never produced a real best.json — the fric-0.617 "optimum" was the test stub's), the material card's evidence citation was corrected in v1.0.1 (parameters/responses/validation unchanged, schema-valid), and the correction is recorded in [results/phase9-drum/NOTES.md](results/phase9-drum/NOTES.md).
- **Stop must walk the process tree**: each `mpirun` runs in its own session (`start_new_session`, the Phase-6 zombie defense), so killing the optimizer's process group alone would orphan in-flight sims for up to `wall_limit`. `ui_state.stop_run` snapshots descendant pgids via `ps -axo pid=,ppid=,pgid=` *before* signaling — verified live: 13 processes (optimizer + 4 detached 2-rank sims) all dead, zero orphans.
- **macOS `ps` rewrites argv[0]** to the resolved framework binary (the venv symlink disappears), so the pidfile's liveness guard must match on the *arguments* (`optimize.py run --config …`), never the executable path. PID-reuse is guarded the same way: an alive pid with the wrong cmdline reads as stale.
- Precedence is explicit CLI flag > config > built-in default (run-arg defaults became `None` sentinels), and `save_config` is the only serializer — the UI never writes JSON itself. `config.json` is committed; `study.db`/`run.log`/`run.pid` are git-ignored and regenerate from it plus the shared cache.

**Premium upgrade (2026-06-13).** The cockpit was rebuilt to mission-control grade without breaking the thin-read-layer charter — `config.json` schema untouched (v1), runner untouched, optuna-dashboard still the fallback:

- **Dark theme** (`.streamlit/config.toml` + [calibration/ui_theme.py](calibration/ui_theme.py)): slate/amber/cyan palette, status pills, carded metrics, Material icons; the same palette/CSS is shared verbatim with the HTML report.
- **Live interactive charts** ([calibration/ui_charts.py](calibration/ui_charts.py), pure plotly builders, headless-tested): convergence vs noise-floor band, the **valley map with the material card's 9 equivalence-family anchors overlaid**, response-vs-target bands, stacked per-response loss breakdown, target bullet chart, trial timeline (cyan cache hits vs amber live sims) + live ETA metric. The matplotlib PNGs remain CLI artifacts; the Run tab no longer polls them. Clicking any chart point opens that trial's detail dialog.
- **Gallery + trial dialog**: filter/sort cards with status-tinted borders; the dialog carries full-res images, the flattened `measured.json` (with the drum's per-frame angle series), and an **in-browser 3-D particle viewer** (plotly WebGL over `measure.read_dump` of the kept final dump — no OVITO in the Streamlit process, ever).
- **Videos** ([calibration/video.py](calibration/video.py), CLI + progress sidecar, spawned detached by `ui_state` because OVITO is not thread-safe off the main thread): per-trial on demand — `flow` (drum steady frames survive pruning), `turntable` (final dump only → any trial), `formation` (aor — re-simulates into a scratch dir inside the seed dir, cache untouched, scratch deleted after encode); H.264 via pinned `imageio-ffmpeg`, GIF fallback via Pillow. `optimize.py run` now spawns `video.py hero` detached at end of run (`--no-hero` opts out) → `hero_aor.mp4`/`hero_drum.mp4` in the study dir, surfaced on the Results tab.
- **Shareable report** ([calibration/report.py](calibration/report.py) + jinja2 template, CLI `report.py --config …` + Results-tab button): one self-contained dark `report.html` — verdict, metric cards, material-card preview, the same interactive figures the UI shows (single source of figure truth), best-trial images (base64), hero videos (embedded ≤ 25 MB), hold-out validation, and the exact CLI replay command.
- **Material inputs are per-study configurable (2026-06-13)** — the Configure tab gained a Material section: **PSD upload (CSV) + editable bin table**, particle density, Young's modulus, timestep (auto Rayleigh-scaled from the smallest grain, anchored to the validated wheat 8e-6 s), and heap particle count (with an insertion-region capacity warning; drum counts auto-scale to keep the published 50% fill). Config schema bumped to **v2** (`material` block; v1 files load unchanged as the wheat default). The engineering contract: **a non-default material joins the params hash** — its own cache namespace, so changed physics can never collide with stale wheat results — while the default omits itself from the hash entirely, preserving every legacy cache key (pinned by regression test against the live cache). Custom materials render per-trial template variants from `templates/*.in.j2` (default render is byte-identical to the static `.in` files, test-pinned); stage boundaries (settle/steady dump steps), wall limits, snapshot color scales, and the formation-video re-sim all follow the material. Verified end-to-end with a real 6–8 mm "maize" LIGGGHTS run (own namespace, measured, rendered). Geometry and protocol knobs (lift speed, drum rpm, wall friction) stay code-level deliberately — lift speed is rate-sensitive (Phase-3) and the meshes/cameras/measurement windows assume the locked geometry.

---

### Phase 9 — Second response

**Goal.** Break the friction valley. Build the second physical + simulated test pair — **drawdown/orifice flow** (mass flow rate; favoured: cheap to build, strong sliding-friction sensitivity) or rotating drum (dynamic angle of repose) — measure it physically with repeats, template it (`templates/drawdown.in`), extend `measure.py`, and add it to the objective. Re-run the optimization multi-response (weighted-sum first; NSGA-II if the trade-off front itself is informative).

**Exit criterion.** A single parameter set matches **both** responses within their respective measurement spreads; the post-hoc contour plot shows the valley collapsed to a localized optimum.

**Dependencies.** Phase 8 (single-response pipeline proven end-to-end).

**Risks.** The two tests may genuinely conflict (model-form error — e.g. real particle shape effects a sphere model cannot capture). Then the honest outcomes are multisphere particle shapes (LIGGGHTS supports them, at runtime cost) or a documented tolerance trade-off — Checkpoint 4 forces that decision explicitly.

**Lessons learned.** *(drum + probes completed 2026-06-12 — templates [drum.in](templates/drum.in)/[drawdown.in](templates/drawdown.in), modules extended, full record in [results/phase9-drum/NOTES.md](results/phase9-drum/NOTES.md))*

- **The drum was chosen (published wheat target) and built — and proved degenerate with the heap.** Along the iso-static-AoR valley the drum angle moves < 1° under both cover protocols: for single spheres + epsd2, heap and slow-drum angles are governed by the same effective bulk friction. A second response only breaks degeneracy if its iso-lines *cross* the first's — regime diversity, not test diversity. The planned multi-response optimization was correctly cancelled by the M4 gate (flat combined loss), saving the ~5 h study.
- **Checkpoint 4 closed on its own fallback clause, with evidence:** all 9 valley anchors match BOTH responses within spread; the representative member (fric 0.40 / μ_r 0.137 / e 0.58) verified at 5 seeds — heap 26.4 ± 0.6°, drum 38.1 ± 0.2°, bulk density 782 kg/m³ uncalibrated. The deliverable is the **equivalence family** fric 0.25–0.60 ↔ μ_r 0.22–0.12 (rest free).
- **The 18-sim drawdown probe found the real degeneracy breaker:** orifice flow rate falls monotonically 46.3 → 40.0 g/s along the valley (8.2× seed noise, Spearman −0.9, ~140 s/run). The originally-favoured response wins after all; what it lacks is a physical target (flow rate is geometry-bound — needs literature wheat discharge data Beverloo-scaled to our D_o = 22 mm, with stated uncertainty).
- **The ground-truth doc's drum number was an AI-extraction artifact** (recorded 24.3 ± 1.2°; the paper says 36.17°, pooled σ ≈ 3.1°). Caught by the M0 read-the-source gate before any compute targeted the wrong value. Their calibrated set was also mis-recorded (actually μ_s 0.15 / μ_r 0.36 on 7-sphere clumps, valley explicitly acknowledged).
- **Cover physics is first-order in thin drums:** frictionless end caps under-read ~6°; a *static* frictional cap locks the bed entirely (1–2°) — the published acrylic cover co-rotates, so the faithful model is a separate co-rotating cap mesh at the published wheat–acrylic friction (0.36/0.29). The "quasi-2D frictionless slice" idealization was the root cause of the first (false) NO-GO.
- Engine gotchas for the record: one `wall/gran` mesh fix per sim (multi-mesh walls share it; mid-run removal = `fix move/mesh` the part away, not unfix); `particles_in_region` over-inserts if the region misses wall-adjacent centers; `floor(x+0.5)` not `ceil()` for stage arithmetic; thermo and referenced fixes must share a compatible nevery.
- **The target search closed the phase:** a verified multi-source literature review ([experiments/drawdown-flowrate-literature.md](experiments/drawdown-flowrate-literature.md)) found no wheat-fitted Beverloo constants and no wheat discharge data near our 22 mm orifice — the best constructible target (soft 40 ± 12 g/s) is wider than the family's entire 6.8 g/s span, i.e. a consistency check the family passes, not a calibration. **A unique point awaits a *measured* flow rate** (±2 g/s suffices; the drawdown rig — bin, orifice plate, scale — is the cheapest of the three tests to build physically). When that number exists, the remaining work is mechanical: add drawdown to `runner.RESPONSES` (two precedents in code), switch on the third loss term, re-run the built optimizer, verify at 5 seeds.

→ **Checkpoint 4**: Calibrated set matches reality within tolerance? — **✅ qualified PASS (2026-06-12)**, family-level match per the fallback clause; the literature cannot tighten it further (drawdown target research closed the question), a physical flow measurement can. Details in the checkpoint table above.

---

### Phase 10 — Hold-out validation + material card

**Goal.** Prove the parameters describe the **material**, not the calibration tests. Simulate a held-out scenario never used in calibration and compare against a physical measurement of the same. *(Phase 9 left a ready-made candidate: Sugirbay's 45°-inclined-drum measurements — verified numbers per shell material, e.g. acrylic 43.65° — never calibrated against, needing only a tilt-axis variant of the proven drum template. A different cylinder diameter for the heap test remains the simpler alternative.)* Then ship the deliverable: `materials/<name>.json` — the calibrated values, their uncertainty, the contact model and LIGGGHTS version they belong to, the evidence (links to trials, plots, measured data), and the validation result.

**Exit criterion.** Held-out prediction within (a pre-stated multiple of) measurement spread; the material card validates against a JSON schema and a fresh `runner.evaluate` using only the card reproduces the calibrated responses.

**Dependencies.** Phase 9.

**Risks.** Validation failure sends us back with information — which response family failed says whether the gap is parameters (re-calibrate with the held-out test added) or model form (particle shape, cohesion model).

**Lessons learned.** *(completed 2026-06-12 — template [templates/drum45.in](templates/drum45.in), validation [calibration/validate.py](calibration/validate.py), card [materials/wheat.json](materials/wheat.json) + [schema](materials/schema.json) via [calibration/material_card.py](calibration/material_card.py), full record in [results/phase10-validation/NOTES.md](results/phase10-validation/NOTES.md))*

- **Exit criterion met, verdict pre-registered — and the pass is a *qualified* one.** The Sugirbay 45°-inclined acrylic drum (43.65° ± 2.92, Table 1/2 — never used in calibration) was predicted at **48.93° ± 0.21** (5 seeds): |error| 5.28° ≤ the pre-stated 2σ₄₅ = 5.84°, i.e. a **marginal 1.8σ pass carrying a shared +5° systematic** (seed noise 0.2–0.7° rules out chance). 2σ is a defensible bar — the physical repeats themselves span 39.7–46.3° — but the claim this licenses is "the family is consistent with the material at measurement precision", NOT degree-level parameter accuracy (see the length-systematic bullet). `validate.py run` refuses to start without `acceptance.json` — pre-registration enforced by code, stated before the first frame was simulated, which is the only reason a marginal pass is meaningful at all. The card validates against `materials/schema.json` and `material_card.py reproduce` replays heap 26.39° / drum 38.06° / ρ 782 from the card alone.
- **The tilt is a gravity rotation, not a mesh rotation** — `region cylinder` and primitive walls are axis-aligned only, so tilting g in the drum frame reuses every Phase-9 mesh, the insertion region, and the backstops; the camera-concentric published measurement becomes a plain x–z line fit in a cover-adjacent y-slab with no coordinate transform.
- **The 45° drum is family-degenerate too** (span 0.21° across fric 0.25–0.60, as pre-stated: all walls pinned to published wheat–acrylic values → wall-dominated) — the hold-out validates the *equivalence family*, the honest Phase-9 deliverable, and cannot localize within it. The drawdown flow rate remains the only known family-breaker.
- **The halved drum length costs ≈ −9.5° at 45°** (one run at the published 50 mm: 39.3–39.8° vs 48.93° at 25 mm) — the cover effect dominates exactly where the trace is measured, an order of magnitude beyond its vertical-drum footprint. Both geometries land inside 2σ from opposite sides; the fair-geometry residual is ~−4° of model form (single spheres; wall pair calibrated on the source's clumps). Documented in the card's deviations.
- **45° physics is slower and noisier than vertical:** transient ~7 s of rotation (vs 3 s) → SPINUP 7.0 s, ~17 min/run; the cover-slab flow is intermittent (avalanche cycle 2–3 s, frame σ ~2–2.7° — consistent with the published 45° repeats scattering 39.7–46.3°), so the window must average ≥ 2 cycles and the 1°-drift steadiness guard had to become noise-aware (material AND > 2 se) or it false-alarms on cycle phase at steady state.
- **CLI footgun fixed in passing:** `runner.py eval --capfric` defaulted to 0.0 and was injected unconditionally — any drum CLI eval silently ran frictionless covers under a wrong cache hash. Override flags now inject only when given.

---

### Phase 11 — Reproducibility & docs

**Goal.** A stranger (or this machine after a wipe) can reproduce the result. README covering the build recipe (VTK-off, Boost path — the Phase-0 lessons), pinned `requirements.txt`, the measurement protocol, and **one command** (`make calibrate` or `calibration/run_all.sh`) that replays the full pipeline from templates to material card using the cached trials.

**Exit criterion.** Fresh clone + documented steps → smoke test passes and the pipeline replays from cache without edits. The repo on GitHub is the complete artifact.

**Dependencies.** Phase 10.

**Risks.** None notable; discipline work.

**Lessons learned.** _(placeholder)_

---

## Open questions

- ~~**Material choice.**~~ **Resolved (2026-06-11): wheat grain** — dry, cohesionless (no SJKR). See [experiments/ground-truth-wheat-literature.md](experiments/ground-truth-wheat-literature.md).
- ~~**Measurement equipment.**~~ **Mooted (2026-06-11):** no physical sample available — Phase 2 satisfied by a literature substitute with an *assumed* σ = 1.5°. If a sample and rig appear later, the experiments doc is what real measurement replaces.
- ~~**Target tolerance.**~~ **Resolved in practice at Checkpoint 4 (2026-06-12): within measurement spread.** The verdict used each response's σ as stated in the experiments doc (heap ± 1.5° assumed, drum ± 3.1° measured) — the representative set sits at 0.4σ / 0.6σ, comfortably inside both, so no looser engineering tolerance was needed. The honest-uncertainty statement the note asked for ended up living in the *parameters* instead: the equivalence family is the stated tolerance on (μ_s, μ_r).
- ~~**Second test: drawdown or rotating drum?**~~ **Resolved the hard way (2026-06-12): both, in sequence.** The drum was chosen first (published wheat target — though the value this note used to cite, 24.3°, was an extraction artifact; the real target is 36.17° ± 3.1°) and proved **degenerate with the heap** (< 1° variation along the friction valley — slow-flow tests are mutually redundant for single spheres). An 18-sim probe then showed **drawdown/orifice flow discriminates** (46.3 → 40.0 g/s along the valley, 8× noise): the inertial regime separates μ_s from μ_r. The drum stays as a verified secondary response; drawdown is the valley breaker — but the target search (next item) found the literature too soft to use it, so the breaker waits on a physical measurement.
- ~~**Drawdown flow-rate target.**~~ **Researched and closed (2026-06-12): the literature cannot supply a discriminating target.** A verified multi-source search ([experiments/drawdown-flowrate-literature.md](experiments/drawdown-flowrate-literature.md)) found no wheat-fitted Beverloo constants and no wheat data near our orifice scale; the best model-based value is a **soft 40 ± 12 g/s** — wider than the entire family's span (40.0–46.3 g/s), so it confirms the family (all members in band, mild preference for the high-fric end) but cannot pick a point. **Phase 9 therefore closes on the equivalence family.** A unique point becomes reachable when a *measured* target exists: a physical drawdown test (±2 g/s precision suffices — cheapest rig of the three) or the paywalled Chang & Converse 1988 tables + a large-geometry sim. Recorded in the experiments doc.
- **Residual model-form bias at the true 45° geometry** *(opened by Phase 10, 2026-06-12)*. At the published 50 mm drum length the calibrated set under-predicts the 45° angle by ~4° (~1.4σ — inside tolerance, so not blocking). If point accuracy on inclined/wall-dominated responses is ever needed, the named remedies are multisphere particle shapes (closes the sphere-vs-grain gap the single-sphere μ_r can't fully absorb here) and/or directly measured wheat–wall friction (the carried 0.36/0.29 pair was calibrated on the source's 7-sphere clumps). Quantified in [results/phase10-validation/NOTES.md](results/phase10-validation/NOTES.md).
- **Single- vs multi-objective.** Weighted sum is simpler; NSGA-II shows the trade-off front. Lean weighted-sum until the front itself proves informative.
- **Deployment target: Linux** *(stated 2026-06-12)*. Development and calibration to date are on this arm64 MacBook, but the end state runs on a Linux machine. Mostly low-risk: Linux is LIGGGHTS' native platform and the driver is POSIX-portable by construction (plain-text dumps, `-var` templating, SQLite, `os.killpg`; the `ovito` wheel ships manylinux builds and `QT_QPA_PLATFORM=offscreen` is the standard Linux headless pattern). What changes on the target: rebuild `lmp_auto` (keep `USE_VTK = "OFF"` for parity), re-measure the per-run cost datum, raise the `jobs` cap to the new core count, and treat the macOS cache as valid data but **not bit-reproducible** across compilers — re-verify the final calibrated set with a few seeds on the Linux build. **Phase 11's exit criterion must be executed on the Linux box** — that, not this MacBook, is the real "fresh clone reproduces" test; a Dockerfile pinning the LIGGGHTS build becomes the natural delivery vehicle there.
- **Compute budget.** ~~Changes Phase 6's parallelism design.~~ **Resolved for Phase 6 (2026-06-11): this MacBook, auto-sized concurrency.** The runner sets `jobs = clamp((cpu-2)//2, 1, 4)` (= 4 here, 4 sims × 2 ranks), overridable via `--jobs`/`RUNNER_JOBS`; macOS-only, no cross-platform abstraction. If a beefier box/cloud burst appears for the LHS screen or optimizer, only the `jobs` cap (and a rebuilt binary) change — the driver is otherwise machine-agnostic.
- ~~**Particle upscaling.**~~ **Resolved (2026-06-11): not needed.** Wheat-scale spheres (3.4–4.0 mm, 4000 particles) run in 2.8–3.9 min un-coarsened — Phase 3 sized the problem and it fits the budget as-is.
- ~~**μ_r ceiling (from Phase 3, downgraded by Phase 4).**~~ **Resolved (2026-06-12) by the Phase-7 LHS screen.** Sweeping μ_r 0.00–0.25 (widened from the literature 0.15), the 27° target is bracketed *interior* (7 in-band candidates at μ_r 0.12–0.25), not at the ceiling. Rolling friction is the dominant lever and a single sphere needs μ_r ≳ 0.12 to reach 27° (at μ_r < 0.05 even high sliding friction tops out ~17–19°), but the widened range is sufficient — **multisphere is not needed.**

## Repository layout

```
DEM-calibration/
├── ROADMAP.md            ← this file
├── external/             ← LIGGGHTS-PUBLIC source + built binary (done)
├── templates/            ← parameterized LIGGGHTS input scripts (aor.in, drum.in, drum45.in, drawdown.in — all live) + STL generators/meshes
├── calibration/          ← Python driver: runner.py, measure.py, optimize.py, screen.py, valley_check.py, validate.py, material_card.py, ui.py + ui_state.py (the Phase-8.5 cockpit)
├── experiments/          ← ground truth (currently the wheat literature substitute) + protocol
├── materials/            ← calibrated material cards (the deliverable: wheat.json + schema.json)
├── results/              ← trial directories, LHS screen, optimizer studies
└── docs/                 ← knob catalog, notes
```

The architectural pattern — templated engine inputs, a caching evaluation driver, surrogate-assisted search, per-trial visual audit — is engine-agnostic. If LIGGGHTS-PUBLIC is ever swapped for LIGGGHTS-INL, LAMMPS granular, or Yade, only `templates/` and the dump parser change; the pipeline survives.
