# Phase 8 — Optimizer ✅

`calibration/optimize.py` inverts the simulation: target angle of repose in,
contact parameters out. An Optuna **GP-sampler** study over (fric, rollfric,
rest) wraps the cached Phase-6 driver, persists every trial to SQLite, seeds
itself from the Phase-7 LHS results (35 instant cache hits), and minimizes the
σ-normalized AoR error `|AoR_sim − 27| / 1.5` — a loss of 1.0 ≡ off by one σ,
so the seed-noise floor (≈ 0.25) is directly readable on the convergence curve.

## What it does

```python
from calibration import optimize
study = optimize.build_study(sampler="gp")        # SQLite-backed, resumable
optimize.seed_from_lhs(study)                     # Phase-7 rows -> cache hits
study.optimize(optimize.make_objective(n_seeds=2), n_trials=40)
optimize.write_best(study)                        # best.json incl. top-5 valley points
```

```bash
.venv/bin/python calibration/optimize.py run        --trials 100 --sampler gp
.venv/bin/python calibration/optimize.py resume     --trials 36
.venv/bin/python calibration/optimize.py dashboard  --port 8080   # live web UI
.venv/bin/python calibration/optimize.py plot                      # figures + search3d + best.json
.venv/bin/python calibration/optimize.py best       --n 5
```

## Deliverables

| Artifact | What |
|---|---|
| [calibration/optimize.py](../../calibration/optimize.py) | the module |
| [tests/test_optimize.py](../../tests/test_optimize.py) | 15 tests, driver stubbed — no LIGGGHTS |
| `study.db` | SQLite study (git-ignored; replays from `results/cache/`) |
| [best.json](best.json) | best set + top-5 near-tied valley points + target-met verdict |
| [history.png](history.png) | objective vs trial, best-value line, noise-floor reference |
| [importances.png](importances.png) | fANOVA parameter importances |
| [contour.png](contour.png) | the (fric, rollfric) friction valley — the exit-criterion figure |
| [search3d.html](search3d.html) | animated plotly 3-D view of the search through (fric, rollfric, rest) |

## Study design

- **Objective**: `W_AOR · |AoR − 27|/1.5` (weighted-sum form per ROADMAP; the
  bulk-density term is wired but dormant, `W_DENSITY = 0`, until Phase 9 brings
  a trustworthy ρ target + σ_ρ). Failed sims (aor `None`) get a large *finite*
  penalty (100 ≈ 67σ) — not NaN, not pruned — so `best_trial` and the DB schema
  stay uniform and the GP stays well-conditioned.
- **Search space**: the screened, target-bracketing sub-box fric 0.20–0.60 /
  rollfric 0.05–0.25 / rest 0.30–0.70 (⊂ `runner.RANGES`; rollfric < 0.05 was
  shown unreachable in Phase 7). All 3 dims searched — rest deliberately kept
  despite the Phase-7 freeze recommendation, as a live cross-check.
- **Sampler**: `GPSampler` (needs `torch`; `greenlet` speeds its acquisition
  optimization). `--sampler tpe` is the no-torch fallback.
- **Persistence/resume**: SQLite via RDBStorage; same `STUDY_NAME` +
  `load_if_exists` re-attaches. Trials commit individually — a kill loses at
  most the in-flight trial.
- **Seeding**: `enqueue_trial` (not `add_trial`) so each LHS row re-runs through
  the objective and hits the runner cache — every trial in the DB has identical
  structure. NaN-AoR and out-of-bounds rows skipped; hash-guard makes seeding
  idempotent across resumes. 35 of 45 LHS rows were in-bounds; all 35 were
  cache hits (0.8 s for the whole seed pass).

## Results — the exit criteria (2026-06-12)

1. **Converges to a parameter set matching the heap angle within σ — yes.**
   56 completed trials (35 LHS seeds + 21 GP, run stopped early on convergence;
   ROADMAP budget was 50–150). Best: **trial 46, AoR 26.95° (loss 0.036)** at
   fric 0.60 / rollfric 0.120 / rest 0.70 — 0.05° from target, an order of
   magnitude below the noise floor. 9 trials sit at/below the floor; further
   improvement would be chasing seed noise, which is why the run was cut at 56.
2. **Study resumes cleanly after a mid-run kill — yes, tested deliberately.**
   SIGKILL mid-trial → 39 COMPLETE trials preserved, only the in-flight trial
   lost (left as a stale RUNNING row — harmless); `resume` re-attached, seeded 0
   duplicates, and continued. Orphan MPI ranks: the runner's own session-group
   handling plus one `pkill` swept them; nothing leaked into later trials.
3. **The dashboard shows the sliding-vs-rolling-friction valley — yes.**
   [contour.png](contour.png): the near-zero-loss band runs diagonally from
   (fric 0.25, rollfric 0.225) to (fric 0.60, rollfric 0.12) — anti-correlated,
   exactly the degeneracy the ROADMAP predicted. The top-5 in
   [best.json](best.json) are near-ties from *both ends* of the valley.
   In-band trials span **fric 0.248–0.600 at rollfric 0.111–0.246** (24 of 56).

Cross-checks: fANOVA importances **rollfric 0.86 ≫ fric 0.10 ≫ rest 0.04**
independently reproduce the Phase-7 sensitivity ranking; bulk density of the
best trial is 776 kg/m³ (literature ≈ 780) with the density term *off* — the
fixed PSD/particle-density inputs keep landing the packing right for free.

## Cost

21 GP trials × 2 seeds ≈ 42 new sims at ~4.4 min/trial wall (2 seeds in
parallel) ≈ **1.6 h of GP refinement**; the 35-seed warm start was free (cache).
Tests run in ~4 s with the driver stubbed.

## Lessons learned

- **GPSampler pulls in torch (~88 MB wheel)** — it is not in optuna's base
  deps. `greenlet` silences a sequential-L-BFGS fallback warning. fANOVA
  importances additionally need `scikit-learn`. All pinned in requirements.
- **GP exploitation was strikingly efficient: 17 of 21 proposals landed
  in-band** (81%), vs 7 of 45 for the LHS (16%). Warm-starting from screened
  data is worth far more than extra optimizer trials.
- **The optimizer converged at the 4th GP trial** (trial 46 of 75 planned) and
  spent the rest mapping the valley floor. For a 2-effective-dimension problem
  with a 35-point warm start, ~20 GP trials is the right budget, not 40+ — the
  run was stopped early with nothing lost.
- **The best point sits at the fric = 0.60 search-bound edge** (as does much of
  the GP's valley tracing) — with a single AoR target the fric direction is
  essentially unconstrained, so the "optimum" parks wherever the acquisition
  function likes along the valley. This is the cleanest empirical demonstration
  yet that Phase 9's second response is necessary, not optional. Phase 9 should
  also consider widening fric past 0.6 (runner.RANGES allows up to 1.0).
- **Seed noise at the valley floor occasionally exceeds σ** (trial 56:
  aor_std 1.87° on 2 seeds) — single trials can look in-band by luck. The
  2-seed average is fine for optimization, but the *final* calibrated set
  should be verified with more seeds before Checkpoint 4.
- **enqueue_trial + runner cache is the right seeding pattern**: re-running
  seeds through the objective cost 0.8 s total and kept every DB row uniform —
  no hand-built FrozenTrials, no schema drift.
- A stopped run leaves stale RUNNING rows in the study (one per kill). They are
  cosmetic — samplers and `best_trial` ignore them — but `n_trials` in
  best.json counts them; read `top`/`best` rather than raw counts.

## Reproduce

```bash
# live dashboard (separate terminal, auto-refreshes as trials land)
.venv/bin/python calibration/optimize.py dashboard --port 8080

# the study itself — resumable; LHS seeds are cache hits, GP trials simulate
.venv/bin/python calibration/optimize.py run --trials 60 --sampler gp

# figures + animated 3-D search view + best.json from the persisted study
.venv/bin/python calibration/optimize.py plot
.venv/bin/python calibration/optimize.py best --n 5

# tests (driver stubbed, no LIGGGHTS)
.venv/bin/python -m pytest tests/test_optimize.py -q
```

→ **Phase 9 hand-off**: the single-response pipeline is proven end-to-end; the
valley is quantified (fric 0.25–0.60 ↔ rollfric 0.25–0.11, anti-correlated) and
persisted in `study.db` + `best.json`. The second response (drawdown or drum)
must break this degeneracy; every Phase-8 trial is cached and reusable as the
AoR half of the multi-response objective.
