"""Bayesian optimizer for DEM calibration (Phase 8 single-response; Phase 9
two-response).

Inverts the simulation: target bulk responses in, contact parameters out.
Phase 9 searches fric/rollfric/rest for the single set matching BOTH the
static heap AoR (27 +/- 1.5 deg, lifted cylinder) and the drum dynamic AoR
(36.17 +/- 3.1 deg, Sugirbay 2022 protocol) — the second response breaks the
fric<->rollfric degeneracy valley that Phase 8 mapped. Trials persist to a NEW
SQLite study (the Phase-8 study stays frozen in results/phase8-optimizer/ —
its trial values are a different objective and would poison the GP); the M4
valley-check points (both responses cached) are enqueued as seed trials.

The objective is a weighted sum of sigma-normalized errors (each term: 1.0 ==
off by one sigma; weights 1:1 since sigma already encodes the evidence). A
missing response adds FAIL_PENALTY per response — a half-failed candidate is
penalized but stays distinguishable from a fully failed one, and the GP model
stays well-conditioned on finite values.

Visualization: `dashboard` for the live web UI, `plot` for the deliverable
figures incl. the before/after valley-compare contour (the Phase-9 exit
figure) and the animated 3-D search view.

Phase 8.5: every knob (responses + targets/sigma/weights, search bounds,
sampler, budget, paths) can come from a config.json — written by the UI via
save_config, accepted by every CLI verb via --config — so the file, not a
browser session, is the source of truth. Without --config, default_config()
reproduces the hardwired Phase-9 constants exactly.

CLI:
    .venv/bin/python calibration/optimize.py run       [--config cfg.json]
                                                        [--trials 40] [--sampler gp|tpe]
                                                        [--seeds 2] [--jobs N]
                                                        [--no-seed-valley] [--reset]
    .venv/bin/python calibration/optimize.py resume     [--config cfg.json] [...]
    .venv/bin/python calibration/optimize.py dashboard  [--config cfg.json] [--port 8080]
    .venv/bin/python calibration/optimize.py plot       [--config cfg.json]
    .venv/bin/python calibration/optimize.py best       [--config cfg.json] [--n 5]
"""

import argparse
import json
import math
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import optuna  # noqa: E402

from calibration import runner, screen  # noqa: E402

# ------------------------------------------------------------- constants
OUTDIR = REPO_ROOT / "results" / "phase9-drum"
STORAGE_URL = f"sqlite:///{OUTDIR / 'study.db'}"
STUDY_NAME = "aor-drum-wheat-3d"
SEED_CSV = OUTDIR / "valley_check.csv"   # M4 anchors: both responses cached
BEST_JSON = OUTDIR / "best.json"

TARGET_AOR = screen.TARGET_AOR        # 27.0 deg — single source of truth
TARGET_SIGMA = screen.TARGET_SIGMA    # 1.5 deg — calibration tolerance
TARGET_DRUM = 36.17                   # deg — Sugirbay 2022 vertical drum, 5 rpm
SIGMA_DRUM = 3.1                      # deg — their pooled repeat spread (measured!)

# Objective weights: both terms sigma-normalized, so 1:1 = equal evidential
# weight. The bulk-density term stays wired but dormant — density lands ~780
# uncalibrated (Phase 7), so it adds no discrimination.
W_AOR = 1.0
W_DRUM = 1.0
W_DENSITY = 0.0
TARGET_RHO = 780.0                    # kg/m^3 — literature poured bulk density
SIGMA_RHO = 50.0                      # kg/m^3 — placeholder spread for the dormant term

# A failed response (every seed broke) gets a large *finite* penalty PER
# RESPONSE so the GP/TPE model stays well-conditioned (real losses top out ~5)
# and a half-failed candidate stays distinguishable from a fully failed one.
# Not NaN, not pruned — keeps best_trial and the SQLite schema uniform.
FAIL_PENALTY = 100.0

# Search box: rollfric/rest keep the Phase-8 screened bounds; fric widens
# 0.60 -> 0.80 because the Phase-8 optimum parked at the 0.60 edge (the valley
# is unconstrained in fric by a single response — exactly what Phase 9 fixes).
# > 0.8 is outside the plausible wheat literature range. runner.canonical
# still validates against the full RANGES.
SEARCH_BOUNDS = {"fric": (0.20, 0.80), "rollfric": (0.05, 0.25), "rest": (0.30, 0.70)}
DIMS = ("fric", "rollfric", "rest")   # search dimensions, in display order

# Convergence-plateau reference: per-response seed-noise floors in sigma units.
# AoR: 0.37 deg median aor_std (Phase 7). Drum: set from the M2 5-seed study.
AOR_NOISE_DEG = 0.37
DRUM_NOISE_DEG = 0.27                 # M2 5-seed study at (0.40, 0.12): 30.69 ± 0.27 deg


# ------------------------------------------------------------- study config
@dataclass(frozen=True)
class StudyConfig:
    """One calibration study, fully specified. The JSON form (save_config /
    load_config) is what the UI writes and every CLI verb accepts — replaying
    the file through the bare CLI reproduces the identical study. Defaults
    (default_config) equal the module constants, so no config == today."""

    study_name: str
    outdir: Path
    # response name -> {"enabled", "target", "sigma", "weight"}; names must
    # exist in runner.RESPONSES with a "calib" block, holdouts must stay off
    responses: dict
    search_bounds: dict                   # dim -> (lo, hi), within runner.RANGES
    sampler: str = "gp"
    sampler_seed: int = 12345
    n_seeds: int = 2
    trials: int = 40
    jobs: int | None = None
    seed_csv: Path | None = None          # None disables warm-start seeding
    density: dict = field(default_factory=lambda: {
        "weight": 0.0, "target": 780.0, "sigma": 50.0})
    fail_penalty: float = 100.0
    # material inputs (PSD/density/E/dt/n_particles) — None = the wheat
    # default (legacy cache namespace). NEVER searched: fixed physics per
    # study, validated through runner.material_canon at load time.
    material: dict | None = None

    @property
    def storage_url(self) -> str:
        return f"sqlite:///{Path(self.outdir) / 'study.db'}"

    @property
    def best_json(self) -> Path:
        return Path(self.outdir) / "best.json"

    def enabled_responses(self) -> tuple[str, ...]:
        """Enabled response names in registry order (= evaluate_multi order)."""
        return tuple(r for r in runner.RESPONSES
                     if r in self.responses and self.responses[r].get("enabled"))

    def noise_floor(self) -> float:
        """Irreducible combined seed-noise floor in loss units (the dotted
        reference line on the convergence plot)."""
        floor = 0.0
        for r in self.enabled_responses():
            noise = runner.RESPONSES[r]["calib"].get("noise_deg")
            if noise is not None:
                rc = self.responses[r]
                floor += rc["weight"] * noise / rc["sigma"]
        return floor


def default_config() -> StudyConfig:
    """The hardwired Phase-9 setup as a StudyConfig. Reads the module globals
    AT CALL TIME (not def time) so monkeypatched paths in tests are honored —
    the def-time default-arg binding bug this replaces silently wrote a test
    artifact into results/phase9-drum/best.json."""
    return StudyConfig(
        study_name=STUDY_NAME,
        outdir=Path(OUTDIR),
        responses={
            "aor": {"enabled": True, "target": TARGET_AOR,
                    "sigma": TARGET_SIGMA, "weight": W_AOR},
            "drum": {"enabled": True, "target": TARGET_DRUM,
                     "sigma": SIGMA_DRUM, "weight": W_DRUM},
        },
        search_bounds={d: tuple(SEARCH_BOUNDS[d]) for d in DIMS},
        sampler="gp", sampler_seed=12345, n_seeds=2, trials=40, jobs=None,
        seed_csv=Path(SEED_CSV),
        density={"weight": W_DENSITY, "target": TARGET_RHO, "sigma": SIGMA_RHO},
        fail_penalty=FAIL_PENALTY,
    )


def _repo_rel(p) -> str:
    """Serialize a path repo-root-relative when possible (portable to the
    Linux target); absolute otherwise."""
    p = Path(p)
    try:
        return str(p.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(p)


def save_config(cfg: StudyConfig, path: Path) -> Path:
    """Serialize a StudyConfig to config.json. The ONLY config writer in the
    repo — the UI calls this, never serializes JSON itself (single source of
    truth). Round-trips through load_config to a fixed point."""
    payload = {
        "schema_version": 2,
        "study_name": cfg.study_name,
        "outdir": _repo_rel(cfg.outdir),
        "responses": {name: {"enabled": bool(rc["enabled"]),
                             "target": float(rc["target"]),
                             "sigma": float(rc["sigma"]),
                             "weight": float(rc["weight"])}
                      for name, rc in cfg.responses.items()},
        "density": {"weight": float(cfg.density["weight"]),
                    "target": float(cfg.density["target"]),
                    "sigma": float(cfg.density["sigma"])},
        "search_bounds": {d: [float(lo), float(hi)]
                          for d, (lo, hi) in cfg.search_bounds.items()},
        "sampler": cfg.sampler,
        "sampler_seed": cfg.sampler_seed,
        "n_seeds": cfg.n_seeds,
        "trials": cfg.trials,
        "jobs": cfg.jobs,
        "seed_csv": _repo_rel(cfg.seed_csv) if cfg.seed_csv else None,
        "fail_penalty": cfg.fail_penalty,
    }
    if cfg.material is not None:
        payload["material"] = {
            "name": str(cfg.material.get("name", "custom")),
            "particle_density_kgm3": float(cfg.material["particle_density_kgm3"]),
            "psd_mm": [[float(d), float(w)] for d, w in cfg.material["psd_mm"]],
            "youngs_modulus_pa": float(cfg.material["youngs_modulus_pa"]),
            "timestep_s": (float(cfg.material["timestep_s"])
                           if cfg.material.get("timestep_s") else None),
            "n_particles": int(cfg.material["n_particles"]),
        }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")
    return path


def load_config(path: Path) -> StudyConfig:
    """Parse + validate a config.json. Rejects unknown/holdout responses and
    bounds outside runner.RANGES — the config can select responses and move
    targets, but cannot invent calibration physics."""
    raw = json.loads(Path(path).read_text())
    if raw.get("schema_version") not in (1, 2):
        raise ValueError(f"unsupported config schema_version {raw.get('schema_version')!r}")

    material = raw.get("material")          # v1 has none -> wheat default
    if material is not None:
        if not isinstance(material, dict):
            raise ValueError("material must be an object")
        filled = {**{k: v for k, v in runner.WHEAT_MATERIAL.items()}, **material}
        try:                                 # full physical validation
            canon = runner.material_canon(filled)
        except ValueError as err:
            raise ValueError(f"material: {err}")
        material = None if canon is None else filled   # default-equivalent -> None

    responses = {}
    for name, rc in raw["responses"].items():
        spec = runner.RESPONSES.get(name)
        if spec is None or "calib" not in spec:
            raise ValueError(f"unknown response {name!r} "
                             f"(have {[r for r in runner.RESPONSES if 'calib' in runner.RESPONSES[r]]})")
        enabled = bool(rc.get("enabled", False))
        if enabled and spec["calib"]["holdout"]:
            raise ValueError(
                f"response {name!r} is a hold-out (validation scenario) — "
                "calibrating against it would destroy the Phase-10 hold-out")
        sigma = float(rc.get("sigma", spec["calib"]["sigma"]))
        weight = float(rc.get("weight", spec["calib"]["weight"]))
        if sigma <= 0:
            raise ValueError(f"response {name!r}: sigma must be > 0 (got {sigma})")
        if weight < 0:
            raise ValueError(f"response {name!r}: weight must be >= 0 (got {weight})")
        responses[name] = {"enabled": enabled,
                           "target": float(rc.get("target", spec["calib"]["target"])),
                           "sigma": sigma, "weight": weight}
    if not any(rc["enabled"] for rc in responses.values()):
        raise ValueError("no response enabled — nothing to calibrate")

    bounds_raw = raw["search_bounds"]
    if set(bounds_raw) != set(DIMS):
        raise ValueError(f"search_bounds must cover exactly {DIMS} (got {sorted(bounds_raw)})")
    search_bounds = {}
    for d, (lo, hi) in bounds_raw.items():
        lo, hi = float(lo), float(hi)
        rlo, rhi = runner.RANGES[d]
        if not (rlo <= lo < hi <= rhi):
            raise ValueError(f"search_bounds[{d!r}]=({lo}, {hi}) must satisfy "
                             f"{rlo} <= lo < hi <= {rhi} (runner.RANGES)")
        search_bounds[d] = (lo, hi)

    sampler = raw.get("sampler", "gp")
    if sampler not in ("gp", "tpe"):
        raise ValueError(f"unknown sampler {sampler!r} (expected 'gp' or 'tpe')")
    n_seeds = int(raw.get("n_seeds", 2))
    trials = int(raw.get("trials", 40))
    if n_seeds < 1 or trials < 1:
        raise ValueError(f"n_seeds ({n_seeds}) and trials ({trials}) must be >= 1")

    seed_csv = raw.get("seed_csv")
    return StudyConfig(
        study_name=str(raw["study_name"]),
        outdir=REPO_ROOT / raw["outdir"],
        responses=responses,
        search_bounds=search_bounds,
        sampler=sampler,
        sampler_seed=int(raw.get("sampler_seed", 12345)),
        n_seeds=n_seeds,
        trials=trials,
        jobs=raw.get("jobs"),
        seed_csv=(REPO_ROOT / seed_csv) if seed_csv else None,
        density={"weight": float(raw.get("density", {}).get("weight", 0.0)),
                 "target": float(raw.get("density", {}).get("target", TARGET_RHO)),
                 "sigma": float(raw.get("density", {}).get("sigma", SIGMA_RHO))},
        fail_penalty=float(raw.get("fail_penalty", FAIL_PENALTY)),
        material=material,
    )


# ------------------------------------------------------------- objective
def response_loss(value, *, target: float, sigma: float,
                  fail_penalty: float = FAIL_PENALTY) -> float:
    """Sigma-normalized absolute error of one response. None/NaN (failed sim)
    -> fail_penalty, large but finite, so the GP stays well-conditioned and a
    half-failed candidate is distinguishable from a fully failed one."""
    if value is None or not math.isfinite(value):
        return fail_penalty
    return abs(value - target) / sigma


def aor_loss(aor, *, target: float = TARGET_AOR, sigma: float = TARGET_SIGMA) -> float:
    """Sigma-normalized absolute AoR error. None/NaN (failed sim) -> FAIL_PENALTY."""
    return response_loss(aor, target=target, sigma=sigma)


def drum_loss(v, *, target: float = TARGET_DRUM, sigma: float = SIGMA_DRUM) -> float:
    """Sigma-normalized absolute drum-angle error. None/NaN -> FAIL_PENALTY."""
    return response_loss(v, target=target, sigma=sigma)


def objective_from_result(res: dict, cfg: StudyConfig | None = None) -> float:
    """Compose the scalar loss from a runner.evaluate_multi aggregate dict:
    the sum over the config's enabled responses of weight * sigma-normalized
    error (a missing response contributes fail_penalty through its term),
    plus the (default-dormant) bulk-density term. Pure (no simulation) so it
    is unit-testable in isolation."""
    cfg = cfg or default_config()
    loss = 0.0
    for name in cfg.enabled_responses():
        rc = cfg.responses[name]
        key = runner.RESPONSES[name]["calib"]["result_key"]
        loss += rc["weight"] * response_loss(
            res.get(key), target=rc["target"], sigma=rc["sigma"],
            fail_penalty=cfg.fail_penalty)
    if cfg.density["weight"]:
        rho = res.get("bulk_density")
        if rho is not None and math.isfinite(rho):   # dormant term: None -> no penalty
            loss += cfg.density["weight"] * abs(rho - cfg.density["target"]) / cfg.density["sigma"]
    return loss


def params_from_trial(trial: "optuna.Trial", cfg: StudyConfig | None = None) -> dict:
    """Suggest a runner param dict over the config's search bounds (all 3 dims)."""
    bounds = (cfg or default_config()).search_bounds
    return {d: trial.suggest_float(d, *bounds[d]) for d in DIMS}


def _hash_attr(response: str) -> str:
    """user_attr name for a response's params hash: 'hash' for aor (the
    Phase 6-8 legacy name), 'hash_<response>' otherwise (preserves the
    Phase-9 'hash_drum' rows byte-for-byte)."""
    return "hash" if response == "aor" else f"hash_{response}"


def make_objective(*, n_seeds: int = 2, jobs: int | None = None,
                   cfg: StudyConfig | None = None):
    """Closure capturing eval settings -> objective(trial) -> float. Suggests
    params, calls the cached multi-response runner (enabled responses x
    n_seeds sims per trial, one pool wave), stashes observables as trial
    user_attrs (for plotting / best-extraction / the UI gallery), and returns
    the scalar loss."""
    cfg = cfg or default_config()
    responses = cfg.enabled_responses()

    def objective(trial: "optuna.Trial") -> float:
        params = params_from_trial(trial, cfg)
        res = runner.evaluate_multi(params, responses=responses,
                                    n_seeds=n_seeds, jobs=jobs,
                                    material=cfg.material)
        keys = {"bulk_density", "n_ok"}
        for r in responses:
            calib = runner.RESPONSES[r]["calib"]
            keys.update((calib["result_key"], calib["std_key"]))
        for k in sorted(keys):
            trial.set_user_attr(k, res.get(k))
        for r in responses:
            trial.set_user_attr(_hash_attr(r),
                                runner.params_hash(params, r, cfg.material))
        return objective_from_result(res, cfg)

    return objective


# ------------------------------------------------------------- study
def _make_sampler(sampler: str, seed: int):
    if sampler == "gp":
        return optuna.samplers.GPSampler(seed=seed)
    if sampler == "tpe":
        return optuna.samplers.TPESampler(seed=seed, multivariate=True, group=True)
    raise ValueError(f"unknown sampler {sampler!r} (expected 'gp' or 'tpe')")


def build_study(*, sampler: str | None = None, seed: int | None = None,
                reset: bool = False, cfg: StudyConfig | None = None) -> "optuna.Study":
    """Create or load the SQLite-backed study. Same study_name + load_if_exists
    resumes a killed run (per-trial commits -> at most the in-flight trial lost).
    `reset` deletes any existing study first (the only state-changing op)."""
    cfg = cfg or default_config()
    sampler = sampler if sampler is not None else cfg.sampler
    seed = seed if seed is not None else cfg.sampler_seed
    Path(cfg.outdir).mkdir(parents=True, exist_ok=True)
    storage = optuna.storages.RDBStorage(url=cfg.storage_url)
    if reset:
        try:
            optuna.delete_study(study_name=cfg.study_name, storage=storage)
        except KeyError:
            pass
    return optuna.create_study(
        study_name=cfg.study_name, storage=storage,
        sampler=_make_sampler(sampler, seed),
        direction="minimize", load_if_exists=not reset)


def _enqueued_and_done_params(study: "optuna.Study") -> set:
    """Hashes of params already queued or run, so seeding is idempotent on resume."""
    seen = set()
    for t in study.get_trials(deepcopy=False):
        if t.params:
            try:
                seen.add(runner.params_hash({**t.params}))
            except (KeyError, ValueError):
                pass
    return seen


def _within_bounds(params: dict, bounds: dict | None = None) -> bool:
    bounds = bounds if bounds is not None else SEARCH_BOUNDS
    return all(bounds[d][0] <= params[d] <= bounds[d][1] for d in DIMS)


def seed_from_valley(study: "optuna.Study", csv_path: Path | None = None,
                     cfg: StudyConfig | None = None) -> int:
    """Enqueue each M4 valley-check anchor as a starting trial. Those points
    have BOTH responses cached, so each seed trial costs ~0 s and the GP never
    sees a partial-response candidate. The remaining LHS rows are deliberately
    NOT enqueued: each would trigger 2 fresh drum sims for points mostly far
    from the joint optimum — the GP placing those sims itself is strictly
    better. Skips rows missing any enabled response or outside the search
    bounds. Idempotent across resumes. Returns count added."""
    import pandas as pd

    cfg = cfg or default_config()
    csv_path = csv_path if csv_path is not None else cfg.seed_csv
    if csv_path is None or not Path(csv_path).exists():
        return 0
    df = pd.read_csv(csv_path)
    value_cols = [runner.RESPONSES[r]["calib"]["result_key"]
                  for r in cfg.enabled_responses()]
    df = df.dropna(subset=[c for c in value_cols if c in df.columns])
    seen = _enqueued_and_done_params(study)
    n = 0
    for _, r in df.iterrows():
        params = {d: float(r[d]) for d in DIMS}
        if not _within_bounds(params, cfg.search_bounds):
            continue
        h = runner.params_hash(params)
        if h in seen:
            continue
        study.enqueue_trial(params, skip_if_exists=True)
        seen.add(h)
        n += 1
    return n


# ------------------------------------------------------------- results
def _first_trial_dir(attrs: dict, cfg: StudyConfig) -> str | None:
    """Reconstruct the first-seed trial dir from the first enabled response
    whose hash user_attr is present (aor's prefix is '' — legacy layout)."""
    for r in cfg.enabled_responses():
        h = attrs.get(_hash_attr(r))
        if h:
            prefix = runner.RESPONSES[r]["dir_prefix"]
            return str(runner.CACHE / f"{prefix}{h}" / f"seed{runner.SEEDS[0]}")
    return None


def best_records(study: "optuna.Study", n: int = 5,
                 cfg: StudyConfig | None = None) -> list[dict]:
    """Top-N completed trials by loss (ascending), with observables and the
    reconstructed first-seed trial dir. Surfaces several near-tied valley points,
    not just the single best."""
    cfg = cfg or default_config()
    done = [t for t in study.get_trials(deepcopy=False)
            if t.state == optuna.trial.TrialState.COMPLETE and t.value is not None]
    done.sort(key=lambda t: t.value)
    out = []
    for t in done[:n]:
        rec = {
            "trial": t.number,
            "loss": t.value,
            "params": {d: t.params.get(d) for d in DIMS},
        }
        for r in cfg.enabled_responses():
            calib = runner.RESPONSES[r]["calib"]
            for k in (calib["result_key"], calib["std_key"]):
                rec[k] = t.user_attrs.get(k)
        rec["bulk_density"] = t.user_attrs.get("bulk_density")
        rec["n_ok"] = t.user_attrs.get("n_ok")
        for r in cfg.enabled_responses():
            rec[_hash_attr(r)] = t.user_attrs.get(_hash_attr(r))
        rec["trial_dir"] = _first_trial_dir(t.user_attrs, cfg)
        out.append(rec)
    return out


def _all_bands_met(rec: dict | None, cfg: StudyConfig | None = None) -> bool:
    """The calibration verdict: EVERY enabled response inside its sigma band."""
    cfg = cfg or default_config()
    if not rec:
        return False
    for r in cfg.enabled_responses():
        rc = cfg.responses[r]
        v = rec.get(runner.RESPONSES[r]["calib"]["result_key"])
        if v is None or abs(v - rc["target"]) > rc["sigma"]:
            return False
    return True


_both_bands_met = _all_bands_met        # legacy alias (Phase-9 name)


def write_best(study: "optuna.Study", path: Path | None = None, *, n: int = 5,
               cfg: StudyConfig | None = None) -> Path:
    """Persist the best set + top-N table + an all-bands verdict to best.json.
    path=None resolves to cfg.best_json AT CALL TIME (the def-time default-arg
    bug here is what contaminated results/phase9-drum/best.json with a test
    artifact)."""
    cfg = cfg or default_config()
    path = Path(path) if path is not None else cfg.best_json
    records = best_records(study, n=n, cfg=cfg)
    best = records[0] if records else None
    payload = {
        "study_name": study.study_name,
        "targets": {r: {"target": cfg.responses[r]["target"],
                        "sigma": cfg.responses[r]["sigma"],
                        "weight": cfg.responses[r]["weight"]}
                    for r in cfg.enabled_responses()},
        "n_trials": len(study.get_trials(deepcopy=False)),
        "best": best,
        "target_met": _all_bands_met(best, cfg),
        "top": records,
    }
    if cfg.material is not None:           # provenance: which physics was run
        payload["material"] = cfg.material
    # legacy top-level keys (Phase-9 consumers: material_card.py evidence)
    if "aor" in cfg.responses:
        payload["target_aor"] = cfg.responses["aor"]["target"]
        payload["sigma"] = cfg.responses["aor"]["sigma"]
    if "drum" in cfg.responses:
        payload["target_drum"] = cfg.responses["drum"]["target"]
        payload["sigma_drum"] = cfg.responses["drum"]["sigma"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))
    return path


# ------------------------------------------------------------- plots
def _save_mpl(ax, path: Path, paths: list) -> None:
    import matplotlib.pyplot as plt
    fig = ax.get_figure()
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)
    paths.append(path)


def make_history_plot(study: "optuna.Study", out_path: Path,
                      cfg: StudyConfig | None = None) -> Path:
    """Convergence curve with the combined seed-noise-floor reference line.
    Cheap enough for the UI to poll every few seconds."""
    import matplotlib
    matplotlib.use("Agg")
    import optuna.visualization.matplotlib as ov

    cfg = cfg or default_config()
    ax = ov.plot_optimization_history(study)
    floor = cfg.noise_floor()
    if floor > 0:
        ax.axhline(floor, color="tab:red", ls=":", lw=1.0,
                   label=f"combined seed-noise floor ≈ {floor:.2f}")
        ax.legend(fontsize=8)
    paths: list[Path] = []
    _save_mpl(ax, Path(out_path), paths)
    return paths[0]


def make_contour_plot(study: "optuna.Study", out_path: Path) -> Path:
    """fric-rollfric loss contour (the valley view). UI-pollable."""
    import matplotlib
    matplotlib.use("Agg")
    import optuna.visualization.matplotlib as ov

    ax = ov.plot_contour(study, params=["fric", "rollfric"])
    paths: list[Path] = []
    _save_mpl(ax, Path(out_path), paths)
    return paths[0]


def make_plots(study: "optuna.Study", outdir: Path | None = None,
               cfg: StudyConfig | None = None) -> list[Path]:
    """Static report-grade figures: optimization history (with the noise-floor
    reference line), parameter importances, and the fric-rollfric contour valley.
    Each is guarded so a near-degenerate study can't abort the others."""
    cfg = cfg or default_config()
    outdir = Path(outdir) if outdir is not None else Path(cfg.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []

    try:
        paths.append(make_history_plot(study, outdir / "history.png", cfg))
    except Exception as err:  # noqa: BLE001
        print(f"history plot skipped: {err}", file=sys.stderr)

    try:
        import matplotlib
        matplotlib.use("Agg")
        import optuna.visualization.matplotlib as ov
        ax = ov.plot_param_importances(study)
        _save_mpl(ax, outdir / "importances.png", paths)
    except Exception as err:  # noqa: BLE001
        print(f"importances plot skipped: {err}", file=sys.stderr)

    try:
        paths.append(make_contour_plot(study, outdir / "contour.png"))
    except Exception as err:  # noqa: BLE001
        print(f"contour plot skipped: {err}", file=sys.stderr)

    # the Phase-9 exit figure needs both aor + drum observables
    if {"aor", "drum"} <= set(cfg.enabled_responses()):
        try:
            paths.append(make_valley_compare(study, outdir / "valley_compare.png"))
        except Exception as err:  # noqa: BLE001
            print(f"valley-compare plot skipped: {err}", file=sys.stderr)

    return paths


def make_valley_compare(study: "optuna.Study",
                        out_path: Path | None = None) -> Path:
    """The Phase-9 exit figure: side-by-side fric x rollfric maps of (a) the
    AoR-only loss recomputed from user_attrs — the degenerate valley — and
    (b) the combined two-response loss — the localized optimum. Same color
    scale, so the collapse is directly readable."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    out_path = Path(out_path) if out_path is not None else default_config().outdir / "valley_compare.png"
    done = [t for t in study.get_trials(deepcopy=False)
            if t.state == optuna.trial.TrialState.COMPLETE
            and t.user_attrs.get("aor") is not None
            and all(d in t.params for d in ("fric", "rollfric"))]
    if len(done) < 6:
        raise ValueError(f"only {len(done)} usable trials")

    x = np.array([t.params["fric"] for t in done])
    y = np.array([t.params["rollfric"] for t in done])
    l_aor = np.array([W_AOR * aor_loss(t.user_attrs.get("aor")) for t in done])
    l_both = np.array([W_AOR * aor_loss(t.user_attrs.get("aor"))
                       + W_DRUM * drum_loss(t.user_attrs.get("drum_aor"))
                       for t in done])
    vmax = float(np.percentile(np.concatenate([l_aor, l_both]), 90))

    fig, axes = plt.subplots(1, 2, figsize=(12, 5), sharey=True)
    for ax, loss, title in (
            (axes[0], l_aor, "AoR-only loss — the Phase-8 valley"),
            (axes[1], l_both, "combined AoR + drum loss — Phase 9")):
        tri = ax.tricontourf(x, y, np.clip(loss, 0, vmax),
                             levels=14, cmap="viridis_r")
        band = loss <= 1.0
        ax.plot(x[~band], y[~band], "o", ms=4, mfc="none", c="0.4")
        ax.plot(x[band], y[band], "o", ms=6, c="tab:red",
                label=f"loss ≤ 1σ (n={int(band.sum())}, "
                      f"fric span {np.ptp(x[band]) if band.any() else 0:.2f})")
        ax.set_xlabel("fric")
        ax.set_title(title, fontsize=10)
        ax.legend(fontsize=8, loc="upper right")
        fig.colorbar(tri, ax=ax, label="loss [σ]")
    axes[0].set_ylabel("rollfric")
    fig.suptitle("valley collapse: one response vs two")
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=140)
    plt.close(fig)
    return out_path


def make_search3d(study: "optuna.Study", out_path: Path | None = None) -> Path:
    """Interactive, animated 3-D plotly view of the search through (fric,
    rollfric, rest) space. Markers are colored by AoR (the target band stands out
    in color); an animation slider plays the trials in search order so you can
    watch the sampler home in on the valley. Read-only on the study — regenerate
    any time, including while a run is live."""
    import plotly.graph_objects as go

    out_path = Path(out_path) if out_path is not None else default_config().outdir / "search3d.html"
    done = [t for t in study.get_trials(deepcopy=False)
            if t.state == optuna.trial.TrialState.COMPLETE
            and t.user_attrs.get("aor") is not None
            and all(d in t.params for d in DIMS)]
    done.sort(key=lambda t: t.number)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if not done:
        go.Figure().write_html(str(out_path), include_plotlyjs="cdn")
        return out_path

    fx = [t.params["fric"] for t in done]
    fy = [t.params["rollfric"] for t in done]
    fz = [t.params["rest"] for t in done]
    aor = [t.user_attrs["aor"] for t in done]
    drum = [t.user_attrs.get("drum_aor") for t in done]
    nums = [t.number for t in done]
    hover = [f"trial {n}<br>AoR {a:.2f}°"
             + (f"<br>drum {d:.2f}°" if d is not None else "")
             + f"<br>fric {x:.3f} rollfric {y:.3f} rest {z:.3f}"
             for n, a, d, x, y, z in zip(nums, aor, drum, fx, fy, fz)]

    marker = dict(size=5, color=aor, colorscale="Viridis", cmin=min(aor), cmax=max(aor),
                  colorbar=dict(title="AoR [deg]"), opacity=0.9,
                  line=dict(width=0.5, color="#333"))

    # static layer: every trial, faint, for context
    base = go.Scatter3d(x=fx, y=fy, z=fz, mode="markers", name="all trials",
                        marker={**marker, "opacity": 0.25}, text=hover,
                        hoverinfo="text")
    # animated layer: reveal trials cumulatively in search order
    frames = []
    for i in range(1, len(done) + 1):
        frames.append(go.Frame(
            name=str(nums[i - 1]),
            data=[go.Scatter3d(
                x=fx[:i], y=fy[:i], z=fz[:i], mode="markers",
                marker={**marker, "color": aor[:i], "cmin": min(aor), "cmax": max(aor)},
                text=hover[:i], hoverinfo="text", name="searched")]))

    fig = go.Figure(
        data=[base, go.Scatter3d(x=fx[:1], y=fy[:1], z=fz[:1], mode="markers",
                                 marker={**marker, "color": aor[:1]},
                                 text=hover[:1], hoverinfo="text", name="searched")],
        frames=frames)
    fig.update_layout(
        title=f"Phase-9 search through (fric, rollfric, rest) — {len(done)} trials, "
              f"targets {TARGET_AOR:g}±{TARGET_SIGMA:g}° AoR + "
              f"{TARGET_DRUM:g}±{SIGMA_DRUM:g}° drum",
        scene=dict(xaxis_title="fric", yaxis_title="rollfric", zaxis_title="rest"),
        updatemenus=[dict(type="buttons", showactive=False, x=0.05, y=0.05,
                          buttons=[
                              dict(label="▶ play", method="animate",
                                   args=[None, {"frame": {"duration": 120},
                                                "fromcurrent": True}]),
                              dict(label="❚❚ pause", method="animate",
                                   args=[[None], {"frame": {"duration": 0},
                                                  "mode": "immediate"}])])],
        sliders=[dict(active=0, currentvalue={"prefix": "trial "},
                      steps=[dict(method="animate", label=str(nums[i]),
                                  args=[[str(nums[i])],
                                        {"frame": {"duration": 0}, "mode": "immediate"}])
                             for i in range(len(done))])])
    # CDN keeps the artifact ~100 KB instead of ~5 MB (plotly.js not inlined)
    fig.write_html(str(out_path), include_plotlyjs="cdn")
    return out_path


# ------------------------------------------------------------- entry point
def _cfg_from_args(args) -> StudyConfig:
    return load_config(Path(args.config)) if getattr(args, "config", None) else default_config()


def _spawn_hero(cfg: StudyConfig) -> None:
    """End-of-run hook: detach `video.py hero --config …` so the finished
    study gets its best-trial showcase videos (Phase 8.5). Fire-and-forget in
    its own session — the optimizer exits immediately and a video failure can
    never change this run's exit status or output. Idempotent downstream
    (hero skips existing artifacts), so resumes re-firing it is free."""
    try:
        import subprocess

        config = Path(cfg.outdir) / "config.json"
        if not config.exists():        # constants-only run (no --config): no hero
            return
        video_py = REPO_ROOT / "calibration" / "video.py"
        log = open(Path(cfg.outdir) / "video.log", "ab")  # noqa: SIM115
        try:
            subprocess.Popen(
                [sys.executable, str(video_py), "hero", "--config", str(config)],
                cwd=REPO_ROOT, stdin=subprocess.DEVNULL,
                stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        finally:
            log.close()
        print("hero video render spawned (video.py hero — see video.log)",
              file=sys.stderr)
    except Exception as err:  # noqa: BLE001 — cosmetics must not fail the run
        print(f"hero video spawn skipped: {err}", file=sys.stderr)


def _run(args, *, reset: bool) -> None:
    optuna.logging.get_logger("optuna").addHandler(__import__("logging").StreamHandler(sys.stderr))
    cfg = _cfg_from_args(args)
    # precedence: explicit CLI flag > config > built-in default
    trials = args.trials if args.trials is not None else cfg.trials
    n_seeds = args.seeds if args.seeds is not None else cfg.n_seeds
    jobs = args.jobs if args.jobs is not None else cfg.jobs
    sampler = args.sampler if args.sampler is not None else cfg.sampler
    study = build_study(sampler=sampler, seed=args.seed, reset=reset, cfg=cfg)
    if not args.no_seed_valley:
        added = seed_from_valley(study, cfg=cfg)
        print(f"enqueued {added} valley-check seed trials", file=sys.stderr)
    print(f"optimizing {trials} trials ({sampler}, {n_seeds} seeds/candidate, "
          f"responses {'+'.join(cfg.enabled_responses())})...", file=sys.stderr)
    study.optimize(make_objective(n_seeds=n_seeds, jobs=jobs, cfg=cfg),
                   n_trials=trials)
    write_best(study, cfg=cfg)
    if not getattr(args, "no_hero", False):
        _spawn_hero(cfg)
    records = best_records(study, n=5, cfg=cfg)
    print(json.dumps({"best": records[0] if records else None,
                      "n_trials": len(study.get_trials(deepcopy=False))}, indent=2))


def _add_run_args(p) -> None:
    # None defaults = "not given": the config (or built-in default) fills in
    p.add_argument("--config", help="config.json (UI-written or hand-rolled)")
    p.add_argument("--trials", type=int, default=None)
    p.add_argument("--seeds", type=int, default=None, help="RNG seeds averaged per candidate")
    p.add_argument("--jobs", type=int, default=None, help="concurrent sims (default: auto)")
    p.add_argument("--sampler", choices=["gp", "tpe"], default=None)
    p.add_argument("--seed", type=int, default=None, help="sampler RNG seed")
    p.add_argument("--no-seed-valley", action="store_true",
                   help="skip valley-check seeding")
    p.add_argument("--no-hero", action="store_true",
                   help="skip the end-of-run hero-video render")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    rn = sub.add_parser("run", help="optimize (create or load study, seed from LHS)")
    _add_run_args(rn)
    rn.add_argument("--reset", action="store_true", help="delete + recreate the study")

    rs = sub.add_parser("resume", help="continue an existing study (no reset, no error if new)")
    _add_run_args(rs)

    dh = sub.add_parser("dashboard", help="launch optuna-dashboard on the live study")
    dh.add_argument("--config", help="config.json (selects the study DB)")
    dh.add_argument("--port", type=int, default=8080)

    pl = sub.add_parser("plot", help="static figures + search3d.html + best.json")
    pl.add_argument("--config", help="config.json (selects the study)")

    bs = sub.add_parser("best", help="print top-N trials as JSON")
    bs.add_argument("--config", help="config.json (selects the study)")
    bs.add_argument("--n", type=int, default=5)

    args = ap.parse_args()

    if args.cmd == "run":
        _run(args, reset=args.reset)
    elif args.cmd == "resume":
        _run(args, reset=False)
    elif args.cmd == "dashboard":
        cfg = _cfg_from_args(args)
        os.execvp("optuna-dashboard",
                  ["optuna-dashboard", cfg.storage_url, "--port", str(args.port)])
    elif args.cmd == "plot":
        cfg = _cfg_from_args(args)
        study = optuna.load_study(study_name=cfg.study_name,
                                  storage=optuna.storages.RDBStorage(cfg.storage_url))
        figs = make_plots(study, cfg=cfg) + [make_search3d(study, cfg.outdir / "search3d.html")]
        write_best(study, cfg=cfg)
        print(json.dumps({"figures": [str(p) for p in figs],
                          "best_json": str(cfg.best_json)}, indent=2))
    elif args.cmd == "best":
        cfg = _cfg_from_args(args)
        study = optuna.load_study(study_name=cfg.study_name,
                                  storage=optuna.storages.RDBStorage(cfg.storage_url))
        print(json.dumps(best_records(study, n=args.n, cfg=cfg), indent=2))


if __name__ == "__main__":
    main()
