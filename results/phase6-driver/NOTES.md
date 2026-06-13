# Phase 6 — Simulation driver (`calibration/runner.py`)

Parameter dict → observables, cached + parallel + fault-tolerant. The glue every
downstream phase (LHS screen, optimizer) calls. Module: [calibration/runner.py](../../calibration/runner.py);
tests: [tests/test_runner.py](../../tests/test_runner.py).

## What it does

`evaluate({"fric": 0.5, "rollfric": 0.12})` canonicalizes the params (defaults,
range validation, 4-dp rounding for stable hashing), runs the first `n_seeds` of
a fixed seed list, averages the successful seeds, and returns
`{"aor", "bulk_density", aor_std, per_seed, trial_dirs, warnings, ...}`. Each
(params, seed) pair is one self-contained trial under
`results/cache/<hash>/seed<seed>/`. `evaluate_batch([...])` flattens all
(candidate, seed) jobs into one shared pool so an overnight screen saturates the
machine instead of serializing per candidate.

CLI: `.venv/bin/python calibration/runner.py eval --fric 0.5 --rollfric 0.12 [--rest .5] [--seeds 2] [--jobs N] [--force]`

## Exit criteria — all met (2026-06-11)

| Criterion | Result |
|---|---|
| `evaluate` returns `{aor, bulk_density}` | **aor 25.86°, ρ 778 kg/m³** at FRIC 0.50 / μ_r 0.12 (2-seed mean) — matches the Phase-5 f50r12 ≈ 25.0° datum |
| repeated call instant from cache | **0.64 s** vs 4:14 for the live run, identical result, zero `mpirun` |
| N candidates concurrent, no oversubscription | 2 sims × 2 ranks ≈ 4 cores (`240–393 % cpu`); auto-`jobs`=4 on this 10-core box |
| kill/rerun resumes from cache | cached candidate returned instantly inside a fresh `evaluate_batch` |
| trial self-contained + pruned | trial dir holds `log`, `run.out`, `measured.json`, `snapshot.png`, `profile_fit.png`, and `post/` with **only** `<tag>_final.liggghts` + `<tag>_50000.liggghts` |
| fault tolerance | fault-injected `gravz=1.0` candidate → **`aor=None`**, batch survived, neighbours unaffected; no orphan `lmp_auto` (`pgrep` empty) |

Observed: 2-seed run FRIC 0.50/μ_r 0.12 → seeds 25.42° / 26.31°, σ 0.44° (< the
Phase-4 0.82° noise floor, as expected for one corner); ρ 778/778. Batch 1-seed
FRIC 0.45/μ_r 0.10 → 22.49°. Per-run wall ≈ 4 min on 2 ranks (unchanged from
Phases 3–5).

## Lessons learned

- **OVITO is not thread-safe — render on the main thread only.** The first cut
  ran the whole `run_one` (including `render.render_trial`) inside the thread
  pool and **segfaulted** in OVITO off the main thread (Qt/OVITO state is
  process-global — the Phase-5 note foreshadowed this). Fix: split the unit of
  work into `_simulate` (cache-check + `mpirun`, the slow thread-safe part) and
  `_finish` (render + measure + prune + JSON). The scheduler parallelizes only
  `_simulate`; `_finish` runs serially on the main thread. Post-processing is
  ~2 s/trial — negligible serialized against ~4 min sims.
- **Cache key = canonical params hash, seed is a separate dimension.** Rounding
  to 4 dp before hashing means `0.50000001` and `0.5` collide (optimizers emit
  near-duplicate floats). `gravz`/`lifth` are in the hash at their
  behaviour-preserving defaults so the Phase-5 fault knobs don't collide with
  normal runs.
- **A recorded failure is *not* a cache hit.** `_cached` returns a result only
  when `measured.json` carries an `aor_deg`; a failed/killed trial (no
  `aor_deg`, or no file) is a miss and reruns. So a transient timeout self-heals
  on resume, while completed good trials are skipped. `_simulate` `rmtree`s a
  stale partial dir before relaunching so `_find_final_dump` can't pick up a
  dead frame.
- **Broken heaps raise inside `measure.py`, not the runner.** The `gravz=1.0`
  run emits a benign `RuntimeWarning: invalid value in scalar divide` (centroid
  of zero static particles) and `measure_heap` raises downstream; `_finish`
  catches *any* exception, records `{"failed": true, "error": ...}`, and returns
  a sentinel so the optimizer can penalize rather than the batch dying.
- **Gotchas honoured from Phases 3/5:** `MESH` passed as `os.path.relpath` from
  the trial cwd (space-free — the repo root has a space); `stdin=DEVNULL` on
  every launch; only `SEED` varied (template primes left distinct);
  `start_new_session=True` + `os.killpg` on `TimeoutExpired` (no zombies
  confirmed).
- **`results/cache/` is git-ignored** — auto-generated, hash-named, not
  committed evidence (`post/` was already ignored).

## Reproduce

```bash
# unit tests (no engine, ~4 s)
.venv/bin/python -m pytest tests/test_runner.py -q

# single candidate, 2 seeds (~4 min), then instant cache hit on re-run
.venv/bin/python calibration/runner.py eval --fric 0.5 --rollfric 0.12 --seeds 2
.venv/bin/python calibration/runner.py eval --fric 0.5 --rollfric 0.12 --seeds 2   # ~0.6 s

# batch: cached + fresh + fault-injected broken candidate
.venv/bin/python -c "from calibration import runner; \
print(runner.evaluate_batch([{'fric':0.5,'rollfric':0.12}, {'fric':0.45,'rollfric':0.10}, \
{'fric':0.4,'rollfric':0.05,'gravz':1.0,'lifth':0.005}], n_seeds=1))"
```
