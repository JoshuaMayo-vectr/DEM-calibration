# DEM Calibration Pipeline — Big-Picture Roadmap

## Progress at a glance

| # | Phase | Status |
|---:|---|:---:|
| 0  | Toolchain foundations (LIGGGHTS build, OVITO, Python env, repo scaffold) | ✅ |
| 1  | LIGGGHTS familiarization (tutorials, contact-model catalog, knobs & limits) | ✅ |
| 2  | Physical ground truth (material, PSD, densities, measured angle of repose) | ✅ (literature substitute) |
| ⚑  | **Checkpoint 1 — Stack viable & targets measurable** | ✅ (via literature substitute) |
| 3  | Parameterized angle-of-repose simulation template | ✅ |
| 4  | Automated measurement module (heap-angle fit, bulk density, noise floor) | ⬜ |
| 5  | Visualization layer (OVITO interactive + headless snapshots + audit plots) | ⬜ |
| ⚑  | **Checkpoint 2 — Simulation credible & objective trustworthy** | ⬜ |
| 6  | Simulation driver (templating, parallel execution, result cache) | ⬜ |
| 7  | Latin-hypercube screen & sensitivity analysis | ⬜ |
| ⚑  | **Checkpoint 3 — Target reachable inside parameter ranges** | ⬜ |
| 8  | Optimizer (Optuna Bayesian/TPE; pymoo NSGA-II if multi-objective) + dashboard | ⬜ |
| 9  | Second response — drawdown/drum test breaks the friction degeneracy | ⬜ |
| ⚑  | **Checkpoint 4 — Calibrated set matches reality within tolerance** | ⬜ |
| 10 | Hold-out validation + material card deliverable | ⬜ |
| 11 | Reproducibility & docs (pinned env, one-command rerun) | ⬜ |

Legend: ✅ complete · 🟡 in progress · ⬜ not started · ⏸ paused/blocked · ⚑ checkpoint

## Checkpoints

Checkpoints are **explicit go/no-go decision moments** between phases — not process gates between every phase. They exist because the plan makes technical and physical bets that we can only validate by running into reality. At each checkpoint we stop, evaluate against named criteria, and decide: continue / pivot / cut scope / stop.

| ⚑ | After phase | Question | If "no", what we do |
|---|---|---|---|
| **1** | Phase 2 | **Do we have a working simulation stack AND real measured targets with known spread?** LIGGGHTS runs reliably on this machine, the tutorials behave as documented, and we hold ≥ 5 repeats of a measured angle of repose (plus particle/bulk density) for the chosen material, with the repeat spread quantified. | Fix the toolchain (fall back to LIGGGHTS-INL or LAMMPS granular if 3.8.0 proves broken for our contact models) or simplify the measurement protocol — before writing any pipeline code. |
| **2** | Phase 5 | **Is the simulation credible and the objective trustworthy?** The simulated heap responds plausibly and monotonically to friction changes, the automated angle measurement agrees with manual measurement on rendered output to ±1°, and the seed-to-seed noise floor is below the measured physical spread. | Fix the physics/template or the measurement code. Do **not** start optimizing on an untrusted objective — every downstream phase inherits its errors. |
| **3** | Phase 7 | **Is the measured target inside the reachable response range, and do ≤ 4 parameters actually matter?** The LHS screen brackets the measured angle of repose, and sensitivity analysis identifies a small set of influential parameters. | Revisit the contact model (add cohesion, switch rolling-friction variant) or particle-scale assumptions (size scaling, shape via multisphere) before burning optimizer compute on an unreachable target. |
| **4** | Phase 9 | **Does the best parameter set match all calibrated responses within measurement spread?** Both the static heap response and the second (flow) response are matched simultaneously by a single parameter set. | Add a response, widen parameter ranges, or accept a documented tolerance; only then proceed to validation. If the valley persists, report it honestly — a family of parameter sets with stated equivalence is still a publishable, usable result. |

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

Visualization is not a separate phase — each phase carries its own piece. Three distinct jobs, each mapped to a concrete tool. These are the cross-cutting design contract that Phases 1 / 4 / 5 / 8 all honour.

| Job | Tool | What it answers | Lands in |
|---|---|---|---|
| **Interactive 3D playback** | OVITO desktop (`brew install --cask ovito`) — reads `dump custom` natively, drag-and-drop, scrub the time series | "Does the simulation look physically sane?" | Phase 1 (manual) |
| **Profile-fit audit plot** | matplotlib — binned heap surface + fitted flank line + extracted angle annotated | "Is the objective function measuring what I think it measures?" | Phase 4 |
| **Per-trial headless snapshot** | `ovito` pip package — renders a PNG of the final heap for every trial, no GUI | "Can I skim 100 trials and spot the one where particles exploded?" | Phase 5 |
| **Optimizer dashboard** | optuna-dashboard — live web UI: objective vs. trial, parameter importance, contour plots | "Is it converging, and where's the friction valley?" | Phase 8 |
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

**Lessons learned.** _(placeholder)_

---

### Phase 5 — Visualization layer

**Goal.** Wire up the remaining rows of the visualization palette. Headless per-trial rendering via the `ovito` pip package — every future trial directory gets `snapshot.png` + `profile_fit.png` automatically; a contact-sheet generator tiles N trials into one image for minute-scale skimming of an overnight batch.

**Exit criterion.** Running the Phase-3 template through the driver-to-be's rendering hook produces both images with no GUI; a 20-run contact sheet renders and the one deliberately broken run (gravity flipped) is visually obvious in it.

**Dependencies.** Phase 4 (profile fit to plot), Phase 0 (ovito package).

**Risks.** Headless OVITO rendering on macOS occasionally needs an offscreen-context workaround — budget a half-day, fall back to `dump image` PPMs if it fights back.

→ **Checkpoint 2**: Simulation credible & objective trustworthy?

---

### Phase 6 — Simulation driver

**Goal.** `calibration/runner.py` — parameter dict in, observables out. Renders the jinja2 template (or passes `-var` flags directly), launches `lmp_auto` under MPI, runs 3–4 candidates in parallel (2 ranks each, within the machine's core budget), averages over seeds, invokes `measure.py`, and **caches every result to disk keyed by a params hash** — optimizers revisit old points and simulations are too expensive to repeat. Every trial directory is self-contained: rendered input, log, dumps, snapshots, measured values as JSON.

**Exit criterion.** `runner.evaluate({"fric": 0.5, "rollfric": 0.1, ...})` returns `{"aor": ..., "bulk_density": ...}`; a repeated call returns instantly from cache; 4 candidates run concurrently without oversubscribing the machine; killing and rerunning a batch resumes from cache.

**Dependencies.** Phases 3–5.

**Risks.** Zombie MPI processes on candidate timeout — enforce hard wall-time limits and process-group kills from day one.

**Lessons learned.** _(placeholder)_

---

### Phase 7 — Latin-hypercube screen & sensitivity analysis

**Goal.** ~50–100 runs overnight over literature-informed ranges (sliding friction 0.1–1.0, rolling friction 0.0–0.5, restitution 0.1–0.9, cohesion 0 unless Phase 2 demanded it). Deliverables: sensitivity ranking (which parameters move the angle — restitution usually barely matters for static heaps; **freeze the insensitive ones**), confirmation the measured target lies inside the reachable response range, and a free training set for the surrogate.

**Exit criterion.** Sensitivity bar chart + response scatter exist in `results/lhs-screen/`; the measured angle ± σ is bracketed by the screened responses; the calibration dimension is cut to the parameters that matter (expect ≤ 4).

**Dependencies.** Phase 6.

**Risks.** Target outside the reachable range — that is precisely what Checkpoint 3 exists to catch before optimizer compute is spent.

→ **Checkpoint 3**: Target reachable inside parameter ranges?

---

### Phase 8 — Optimizer

**Goal.** `calibration/optimize.py`. Objective: weighted sum of normalized errors, each term scaled by its measurement uncertainty from Phase 2 — e.g. `w₁·|AoR_sim − AoR_meas|/σ_AoR + w₂·|ρ_sim − ρ_meas|/σ_ρ`. Engine: **Optuna** (TPE/GP sampler), trials persisted to SQLite so runs survive kills and resume; optuna-dashboard live during the run; LHS results enqueued as seed trials. If Phase 9 goes multi-objective: **pymoo NSGA-II**, population ~20, seeded from the same data. Optional hybrid at zero extra cost: fit a Gaussian-process surrogate on all cached runs, run the GA on the surrogate, verify only its proposed optima with real simulations.

**Exit criterion.** An overnight run (50–150 trials) converges to a parameter set matching the heap angle within σ; the study resumes cleanly after a mid-run kill; the dashboard shows the expected sliding-vs-rolling-friction valley in the contour plot.

**Dependencies.** Phase 7 (ranges, seeds, frozen parameters).

**Risks.** Converging into the degeneracy valley is *expected*, not failure — it is the signal to proceed to Phase 9. Optimizer chasing seed noise → re-check the Phase-4 noise floor against the convergence plateau.

**Lessons learned.** _(placeholder)_

---

### Phase 9 — Second response

**Goal.** Break the friction valley. Build the second physical + simulated test pair — **drawdown/orifice flow** (mass flow rate; favoured: cheap to build, strong sliding-friction sensitivity) or rotating drum (dynamic angle of repose) — measure it physically with repeats, template it (`templates/drawdown.in`), extend `measure.py`, and add it to the objective. Re-run the optimization multi-response (weighted-sum first; NSGA-II if the trade-off front itself is informative).

**Exit criterion.** A single parameter set matches **both** responses within their respective measurement spreads; the post-hoc contour plot shows the valley collapsed to a localized optimum.

**Dependencies.** Phase 8 (single-response pipeline proven end-to-end).

**Risks.** The two tests may genuinely conflict (model-form error — e.g. real particle shape effects a sphere model cannot capture). Then the honest outcomes are multisphere particle shapes (LIGGGHTS supports them, at runtime cost) or a documented tolerance trade-off — Checkpoint 4 forces that decision explicitly.

→ **Checkpoint 4**: Calibrated set matches reality within tolerance?

---

### Phase 10 — Hold-out validation + material card

**Goal.** Prove the parameters describe the **material**, not the calibration tests. Simulate a held-out scenario never used in calibration (different cylinder diameter, or the drum if drawdown was calibrated) and compare against a physical measurement of the same. Then ship the deliverable: `materials/<name>.json` — the calibrated values, their uncertainty, the contact model and LIGGGHTS version they belong to, the evidence (links to trials, plots, measured data), and the validation result.

**Exit criterion.** Held-out prediction within (a pre-stated multiple of) measurement spread; the material card validates against a JSON schema and a fresh `runner.evaluate` using only the card reproduces the calibrated responses.

**Dependencies.** Phase 9.

**Risks.** Validation failure sends us back with information — which response family failed says whether the gap is parameters (re-calibrate with the held-out test added) or model form (particle shape, cohesion model).

**Lessons learned.** _(placeholder)_

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
- **Target tolerance.** How close is "matches physical reality" — within measurement spread, or a stated engineering tolerance (e.g. ±2°)? Needed before Checkpoint 4 is decidable. *With the literature substitute, the floor is the assumed σ = 1.5° — but since the target itself is synthetic, an engineering tolerance statement matters more, not less.*
- **Second test: drawdown or rotating drum?** Drawdown is cheaper to build physically; the drum gives a richer dynamic response. Decide at Phase 9 start. *Note: with no physical sample, the second response must also come from literature — drum data for wheat is well published (e.g. Sugirbay 2022: 24.3° ± 1.2°), which may tip the choice toward the drum.*
- **Single- vs multi-objective.** Weighted sum is simpler; NSGA-II shows the trade-off front. Lean weighted-sum until the front itself proves informative.
- **Compute budget.** Calibration on this MacBook alone, or is a beefier box/cloud burst available for the LHS screen and optimizer runs? Changes Phase 6's parallelism design.
- ~~**Particle upscaling.**~~ **Resolved (2026-06-11): not needed.** Wheat-scale spheres (3.4–4.0 mm, 4000 particles) run in 2.8–3.9 min un-coarsened — Phase 3 sized the problem and it fits the budget as-is.
- **μ_r ceiling (new, from Phase 3).** The 27° target is only reached near the top of the rolling-friction range (26.1° at μ_r = 0.15); published wheat friction values give only ~18° with single spheres. Does Phase 7 widen the μ_r range above 0.15, or is multisphere the honest fix? Decide at Checkpoint 3.

## Repository layout

```
DEM-calibration/
├── ROADMAP.md            ← this file
├── external/             ← LIGGGHTS-PUBLIC source + built binary (done)
├── templates/            ← parameterized LIGGGHTS input scripts (aor.in done; drawdown.in at Phase 9) + STL generator/meshes
├── calibration/          ← Python driver: runner.py, measure.py, optimize.py
├── experiments/          ← ground truth (currently the wheat literature substitute) + protocol
├── materials/            ← calibrated material cards (the deliverable)
├── results/              ← trial directories, LHS screen, optimizer studies
└── docs/                 ← knob catalog, notes
```

The architectural pattern — templated engine inputs, a caching evaluation driver, surrogate-assisted search, per-trial visual audit — is engine-agnostic. If LIGGGHTS-PUBLIC is ever swapped for LIGGGHTS-INL, LAMMPS granular, or Yade, only `templates/` and the dump parser change; the pipeline survives.
