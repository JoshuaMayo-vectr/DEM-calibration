"""Simulation driver for DEM calibration (Phase 6).

Parameter dict in, observables out. `evaluate({"fric": 0.5, "rollfric": 0.1})`
renders templates/aor.in via -var flags, launches lmp_auto under MPI (one run
per RNG seed), averages the seeds, measures + renders each trial, and caches
every result to disk keyed by a params hash — optimizers revisit old points and
each DEM run costs ~4 minutes, so nothing is ever recomputed.

A single simulation = one (params, seed) pair = one self-contained trial dir
under results/cache/<hash>/seed<seed>/ holding the log, the final + settle
dumps (the ~142 intermediates are pruned after measurement), snapshot.png,
profile_fit.png and measured.json (the Phase-6 contract render.py's contact
sheet reads back).

Reuses calibration.render.render_trial as the post-run hook (snapshot + Phase-4
measurement + audit plot in one call). macOS/POSIX only — process-group kill on
timeout via os.killpg; the lmp_auto binary is the arm64 macOS Phase-0 build.

CLI:
    .venv/bin/python calibration/runner.py eval \
        --fric 0.5 --rollfric 0.12 [--rest 0.5] [--seeds 2] [--jobs N]
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from statistics import mean, pstdev

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from calibration import render  # noqa: E402

# ------------------------------------------------------------- constants
LMP = REPO_ROOT / "external" / "LIGGGHTS-PUBLIC" / "src" / "lmp_auto"
TEMPLATE = REPO_ROOT / "templates" / "aor.in"   # kept: legacy alias (= RESPONSES["aor"])
MESH = REPO_ROOT / "templates" / "meshes" / "cylinder_r0.040_h0.100.stl"
CACHE = REPO_ROOT / "results" / "cache"

MPIRUN = "mpirun"
NRANKS = 2              # 2 MPI ranks per run — the Phase 3-5 datum (~4 min/run)
WALL_LIMIT = 600        # s; ~2.5x the observed ~240 s run, bounds zombie MPI
SETTLE_STEP = 50000     # template settle stage end (0.4 s / dt 8e-6) — bulk-density dump

# Response registry (Phase 9): one simulated test per response, selected by
# the response= kwarg throughout. The "aor" entry reproduces the Phase 6-8
# behavior byte-for-byte — same canonical dict, same hash, same cache layout
# (dir_prefix "") — so the existing results/cache/<hash>/ dirs stay valid.
RESPONSES = {
    "aor": {
        "template": TEMPLATE,
        "mesh": MESH,
        "success_key": "aor_deg",
        "dir_prefix": "",
        "tag_prefix": "",
        "wall_limit": WALL_LIMIT,
        # Calibration metadata (Phase 8.5): the single source the UI checkbox
        # list, the optimizer objective and the gallery all read. result_key/
        # std_key name the evaluate_multi aggregate fields; fit_png the audit
        # plot each trial dir carries; target/sigma the ground-truth band
        # (test-pinned against screen.TARGET_AOR); noise_deg the seed-noise
        # floor; holdout=True marks a response that must never be calibrated
        # against (config validation rejects it, the UI disables it).
        "calib": {
            "label": "Heap AoR (lifted cylinder)",
            "result_key": "aor",
            "std_key": "aor_std",
            "fit_png": "profile_fit.png",
            "target": 27.0,          # deg — literature wheat (Phase 2)
            "sigma": 1.5,            # deg — assumed spread = tolerance
            "noise_deg": 0.37,       # Phase-7 median aor_std
            "weight": 1.0,
            "holdout": False,
        },
    },
    "drum": {
        "template": REPO_ROOT / "templates" / "drum.in",
        "mesh": REPO_ROOT / "templates" / "meshes" / "drum_r0.075_l0.025.stl",
        # the co-rotating acrylic cover (separate mesh, own friction pair) —
        # a static frictional cap is unphysical and the frictionless one
        # under-reads ~5-7 deg vs the published cover protocol (M4 finding)
        "caps_mesh": REPO_ROOT / "templates" / "meshes" / "drum_caps_r0.075_l0.025.stl",
        "success_key": "drum_aor_deg",
        "dir_prefix": "drum-",
        "tag_prefix": "drum",       # no hyphen: render's _<step> regex stays unambiguous
        # ~8-10 min/run measured (the flowing bed + rotating meshes cost ~2x
        # the aor template per particle-step) — the documented deviation from
        # the 2-5 min guideline
        "wall_limit": 1200,
        # settle (100k) + spin-up (375k) steps; frames >= this are the
        # measurement window and survive pruning
        "steady_step": 475000,
        # (settle_s, spinup_s) — _steady_step_for recomputes the boundary
        # when a custom material changes DT (template arithmetic: floor(x/DT+0.5))
        "stage_s": (0.8, 3.0),
        "calib": {
            "label": "Drum dynamic AoR (vertical, 5 rpm)",
            "result_key": "drum_aor",
            "std_key": "drum_aor_std",
            "fit_png": "drum_fit.png",
            "target": 36.17,         # deg — Sugirbay 2022 vertical drum
            "sigma": 3.1,            # deg — their pooled repeat spread
            "noise_deg": 0.27,       # M2 5-seed study at (0.40, 0.12)
            "weight": 1.0,
            "holdout": False,
        },
    },
    "drum45": {
        # Phase-10 hold-out: 45-deg inclined acrylic drum (gravity tilted in
        # the drum frame; meshes reused). Shell friction is a FIXED protocol
        # input (wheat-acrylic 0.36/0.29, Sugirbay Table 11) — at 45 deg the
        # shell material is significant, so canonical() must NOT mirror the
        # calibrated fric into fricpw for this response.
        "template": REPO_ROOT / "templates" / "drum45.in",
        "mesh": REPO_ROOT / "templates" / "meshes" / "drum_r0.075_l0.025.stl",
        "caps_mesh": REPO_ROOT / "templates" / "meshes" / "drum_caps_r0.075_l0.025.stl",
        "success_key": "drum_aor_deg",
        "dir_prefix": "drum45-",
        "tag_prefix": "drum45",
        # SPINUP 7.0 s (vs 3.0 vertical: weaker in-plane gravity — the M2
        # smokes showed the slab angle climbing until ~7 s of rotation) +
        # MEASURE 6.4 s (the 45-deg slab flow is intermittent, avalanche
        # cycle ~2-3 s — the window must average >= 2 cycles)
        # -> 14.2 s sim vs the vertical drum's 7.0; scale its wall limit
        "wall_limit": 2700,
        # settle (100k) + spin-up (875k) steps at dt 8e-6
        "steady_step": 975000,
        "stage_s": (0.8, 7.0),
        # response-specific measurement: cover-adjacent slab fit + the
        # hold-out target band on the audit plot (measure.py constants)
        "measure_kw": {
            "y_slab": (-0.0135, -0.0051),
            "target": 43.65,
            "target_sigma": 2.92,
        },
        # render a +x side view too — the axial lean against the -y cover
        # is the M2 smoke gate's eyeball check
        "side_view": True,
        "calib": {
            "label": "45° inclined drum (Phase-10 hold-out)",
            "result_key": "drum_aor",
            "std_key": "drum_aor_std",
            "fit_png": "drum_fit.png",
            "target": 43.65,         # deg — Sugirbay acrylic shell
            "sigma": 2.92,           # deg — pooled within-group ANOVA
            "noise_deg": None,
            "weight": 0.0,
            # validation scenario, NEVER a calibration response — calibrating
            # against it would destroy the Phase-10 hold-out
            "holdout": True,
        },
    },
}

# Distinct from the template-internal primes (15485863/15485867/32452843/
# 32452867); deterministic so the cache is reproducible. The first n_seeds are
# used per candidate (Phase 4: averaging 2 gives sigma/sqrt(2) ~ 0.6 deg).
SEEDS = [49979687, 67867967, 86028121, 104395301, 122949823]

# calibration ranges (Phase 7 literature-informed bounds) — validated, not clamped.
# Particle-wall friction (Phase 12) shares the particle-particle ranges: when
# mirrored (the default) it is in-range by construction; when searched
# independently the optimizer needs the same physical envelope.
RANGES = {"fric": (0.1, 1.0), "rollfric": (0.0, 0.5), "rest": (0.1, 0.9),
          "fricpw": (0.1, 1.0), "rollfricpw": (0.0, 0.5)}

ROUND = 4               # decimals for canonicalization -> stable hashing

# ------------------------------------------------------------- material inputs
# The measured physical inputs (PSD, particle density, plus the numerical pair
# E/dt and the heap particle count) — configurable per study since Phase 8.5,
# but NEVER calibrated: the optimizer searches contact parameters only.
#
# Cache-correctness contract: a material that differs from the wheat default
# joins the params hash (its own cache namespace — no stale-physics hits),
# while the DEFAULT material is omitted from the hash entirely so every
# pre-existing results/cache/ entry keeps its byte-identical key.
#
# particletemplate seeds: LIGGGHTS demands all seeds distinct AND prime. The
# first three are the historical wheat seeds (byte-identity for the default
# render); bins 4-8 extend the sequence with verified free primes.
PSD_SEEDS = [15485863, 15485867, 32452843,
             15485917, 15485927, 15485933, 15485941, 15485959]
PSD_DIST_SEED = 32452867
MAX_PSD_BINS = len(PSD_SEEDS)

WHEAT_MATERIAL = {
    "name": "wheat (built-in)",
    "particle_density_kgm3": 1400.0,
    "psd_mm": [[3.4, 0.25], [3.7, 0.50], [4.0, 0.25]],   # [diameter_mm, mass_frac]
    "youngs_modulus_pa": 1.0e7,
    "timestep_s": None,            # None = auto (Rayleigh-scaled; wheat -> 8e-6)
    "n_particles": 4000,           # heap test fill (drums scale by volume)
}

DT_WHEAT = 8.0e-6
_R_MIN_WHEAT = 0.0017              # m — smallest wheat radius (dt scaling anchor)
_NPART_DEFAULT = {"aor": 4000, "drum": 4600, "drum45": 4600}
_MAT_HASH_KEYS = ("psd_mm", "rho", "ymod", "dt", "npart")   # name excluded
# the wheat default in canonical form — material_canon returns None on a match
_WHEAT_CANON_CORE = {"psd_mm": [[3.4, 0.25], [3.7, 0.5], [4.0, 0.25]],
                     "rho": 1400.0, "ymod": 1.0e7, "dt": DT_WHEAT, "npart": 4000}


def _sig(v: float, digits: int = 5) -> float:
    """Round to significant digits (plain round() would zero 8e-6)."""
    return float(f"{float(v):.{digits}g}")


def dt_auto(psd_mm, rho: float, ymod: float) -> float:
    """Rayleigh-criterion-scaled timestep: tau_R ∝ r·sqrt(rho/G), anchored so
    the wheat inputs reproduce the validated 8e-6 s exactly. The template's
    check/timestep/gran guard still verifies the result at run time."""
    r_min = min(float(d) for d, _ in psd_mm) / 2000.0
    dt = DT_WHEAT * (r_min / _R_MIN_WHEAT) * ((rho / 1400.0) * (1.0e7 / ymod)) ** 0.5
    return _sig(dt, 3)


def material_canon(material: dict | None) -> dict | None:
    """Normalize + validate a material block; None means 'the wheat default'.

    Returns None for the default-equivalent material (so a v2 config that
    spells out the wheat values behaves byte-identically to no material at
    all — same hashes, same static template, same cache entries), else a
    canonical dict {name, psd_mm, rho, ymod, dt, npart}. Accepts both the
    user-facing config keys and an already-canonical dict. Raises ValueError
    with a config-error-grade message on anything implausible."""
    if material is None:
        return None
    m = {str(k).lower(): v for k, v in material.items()}
    if "rho" in m:                                   # already canonical
        m = {"name": m.get("name"), "psd_mm": m["psd_mm"],
             "particle_density_kgm3": m["rho"], "youngs_modulus_pa": m["ymod"],
             "timestep_s": m.get("dt"), "n_particles": m["npart"]}

    raw_psd = m.get("psd_mm") or WHEAT_MATERIAL["psd_mm"]
    try:
        bins = sorted(((float(d), float(w)) for d, w in raw_psd), key=lambda b: b[0])
    except (TypeError, ValueError) as err:
        raise ValueError(f"material.psd_mm must be [[diameter_mm, mass_frac], ...]: {err}")
    if not 1 <= len(bins) <= MAX_PSD_BINS:
        raise ValueError(f"material.psd_mm needs 1–{MAX_PSD_BINS} bins (got {len(bins)})")
    for d, w in bins:
        if not 0.5 <= d <= 20.0:
            raise ValueError(f"PSD diameter {d} mm outside the plausible 0.5–20 mm")
        if w <= 0:
            raise ValueError(f"PSD mass fraction must be > 0 (got {w} at {d} mm)")
    total = sum(w for _, w in bins)   # any positive sum normalizes: fractions,
    psd = [[_sig(d), _sig(w / total)] for d, w in bins]   # percent, or ratios

    rho = float(m.get("particle_density_kgm3") or WHEAT_MATERIAL["particle_density_kgm3"])
    if not 100.0 <= rho <= 20000.0:
        raise ValueError(f"particle density {rho} kg/m³ outside 100–20000")
    ymod = float(m.get("youngs_modulus_pa") or WHEAT_MATERIAL["youngs_modulus_pa"])
    if not 1.0e5 <= ymod <= 1.0e9:
        raise ValueError(f"Young's modulus {ymod:g} Pa outside the softened-DEM "
                         "range 1e5–1e9 (real stiffness only slows the timestep)")
    npart = int(m.get("n_particles") or WHEAT_MATERIAL["n_particles"])
    if not 100 <= npart <= 50000:
        raise ValueError(f"n_particles {npart} outside 100–50000")
    dt_raw = m.get("timestep_s")
    dt = _sig(float(dt_raw), 4) if dt_raw else dt_auto(psd, rho, ymod)
    if not 1.0e-7 <= dt <= 5.0e-5:
        raise ValueError(f"timestep {dt:g} s outside 1e-7–5e-5 — check PSD/E inputs")

    canon = {"name": str(m.get("name") or "custom"), "psd_mm": psd,
             "rho": _sig(rho), "ymod": _sig(ymod), "dt": dt, "npart": npart}
    if {k: canon[k] for k in _MAT_HASH_KEYS} == _WHEAT_CANON_CORE:
        return None
    return canon


def _mean_particle_volume(psd_mm) -> float:
    """Number-mean particle volume from mass fractions: v̄ = 1/Σ(wᵢ/vᵢ)."""
    import math
    inv = 0.0
    for d_mm, w in psd_mm:
        r = float(d_mm) / 2000.0
        inv += float(w) / (4.0 / 3.0 * math.pi * r ** 3)
    return 1.0 / inv


# aor insertion region (templates/aor.in: cylinder r 0.0375, z 0.003-0.085)
# and the single-shot density insert/pack reliably achieves with overlapcheck.
# Wheat: 4177 capacity vs the 4000 default — consistent by construction.
_AOR_INSERT_VOLUME = 3.62e-4   # m³
_INSERT_PACK_FRAC = 0.30


def heap_capacity(material: dict | None) -> int:
    """How many particles of this material actually FIT the heap-test
    insertion region. Requesting more does not fail — LIGGGHTS inserts what
    fits and runs a smaller heap — but the UI warns, because a silently
    smaller heap means a noisier angle measurement."""
    mat = material_canon(material)
    psd = (mat["psd_mm"] if mat is not None else WHEAT_MATERIAL["psd_mm"])
    return int(_AOR_INSERT_VOLUME * _INSERT_PACK_FRAC / _mean_particle_volume(psd))


def _npart_for(response: str, mat: dict) -> int:
    """Heap count is the material's n_particles. Drum counts are PROTOCOL-bound
    (the published test is a 50% fill), so they scale only with mean particle
    volume — never with the user's heap-count preference."""
    if response == "aor":
        return mat["npart"]
    ratio = (_mean_particle_volume(WHEAT_MATERIAL["psd_mm"])
             / _mean_particle_volume(mat["psd_mm"]))
    return max(100, round(_NPART_DEFAULT[response] * ratio))


def _steady_step_for(response: str, mat: dict | None) -> int | None:
    """First steady-state dump step. The templates derive stage steps from DT
    (floor(x/DT + 0.5) — the Phase-9 arithmetic), so a custom timestep moves
    the boundary; replicate exactly or pruning eats the measurement window."""
    spec = RESPONSES[response]
    if "steady_step" not in spec:
        return None
    if mat is None:
        return spec["steady_step"]
    import math
    settle_s, spinup_s = spec["stage_s"]
    return (math.floor(settle_s / mat["dt"] + 0.5)
            + math.floor(spinup_s / mat["dt"] + 0.5))


def _settle_step_for(mat: dict | None) -> int:
    """The aor settle-end dump frame (bulk-density measurement). The template
    settles for ceil(0.4 s / DT) steps but dumps on a fixed 5000-step grid, so
    the frame to keep/measure is the last grid step inside the settle stage —
    exactly 50000 at the wheat dt."""
    if mat is None:
        return SETTLE_STEP
    import math
    return max(5000, (math.ceil(0.4 / mat["dt"]) // 5000) * 5000)


def _scaled_wall_limit(response: str, mat: dict | None) -> int:
    """Wall limit scaled by simulation cost: particles × steps (∝ 1/dt)."""
    base = RESPONSES[response]["wall_limit"]
    if mat is None:
        return base
    factor = ((_npart_for(response, mat) / _NPART_DEFAULT[response])
              * (DT_WHEAT / mat["dt"]))
    return min(int(base * max(1.0, factor * 1.3)), 6 * 3600)


def _radius_range(mat: dict | None) -> tuple[float, float] | None:
    """Fixed snapshot color scale for a custom material (None = wheat default)."""
    if mat is None:
        return None
    radii = [float(d) / 2000.0 for d, _ in mat["psd_mm"]]
    lo, hi = min(radii), max(radii)
    if lo == hi:                       # single-bin PSD: pad so the scale is sane
        lo, hi = lo * 0.95, hi * 1.05
    return (lo, hi)


# default template-context strings — must render byte-identically to the
# static .in files (test-pinned); custom values format through _fmt_g
_DEFAULT_PSD_BLOCK = (
    "fix\tpts1 all particletemplate/sphere 15485863 atom_type 1 density constant ${RHO} radius constant 0.0017\n"
    "fix\tpts2 all particletemplate/sphere 15485867 atom_type 1 density constant ${RHO} radius constant 0.00185\n"
    "fix\tpts3 all particletemplate/sphere 32452843 atom_type 1 density constant ${RHO} radius constant 0.0020\n"
    "fix\tpdd1 all particledistribution/discrete 32452867 3 pts1 0.25 pts2 0.50 pts3 0.25")
_DEFAULT_CTX = {"rho": "1400", "ymod": "1.0e7", "dt": "8.0e-6"}


def _fmt_g(v: float) -> str:
    return f"{float(v):.6g}"


def _psd_block(mat: dict) -> str:
    lines = []
    for i, (d_mm, w) in enumerate(mat["psd_mm"]):
        lines.append(
            f"fix\tpts{i + 1} all particletemplate/sphere {PSD_SEEDS[i]} "
            f"atom_type 1 density constant ${{RHO}} radius constant "
            f"{_fmt_g(float(d_mm) / 2000.0)}")
    pairs = " ".join(f"pts{i + 1} {_fmt_g(w)}"
                     for i, (_, w) in enumerate(mat["psd_mm"]))
    lines.append(f"fix\tpdd1 all particledistribution/discrete {PSD_DIST_SEED} "
                 f"{len(mat['psd_mm'])} {pairs}")
    return "\n".join(lines)


def _render_text(response: str, mat: dict | None) -> str:
    """Render a response's .j2 template. mat=None renders the wheat defaults —
    byte-identical to the static .in file (regression-tested), which is why
    the default path can keep using the static file directly."""
    from jinja2 import Template

    j2 = RESPONSES[response]["template"].with_suffix(".in.j2")
    ctx = dict(_DEFAULT_CTX, npart=str(_NPART_DEFAULT[response]),
               psd_block=_DEFAULT_PSD_BLOCK)
    if mat is not None:
        ctx = {"rho": _fmt_g(mat["rho"]), "ymod": _fmt_g(mat["ymod"]),
               "dt": _fmt_g(mat["dt"]), "npart": str(_npart_for(response, mat)),
               "psd_block": _psd_block(mat)}
    return Template(j2.read_text(), keep_trailing_newline=True).render(**ctx)


def _render_template(response: str, mat: dict, trial: Path) -> Path:
    out = trial / f"{response}.in"
    out.write_text(_render_text(response, mat))
    return out


class SimError(RuntimeError):
    """A simulation launch failed (nonzero exit, timeout, or missing binary)."""


# ------------------------------------------------------------- parameters

def canonical(params: dict, response: str = "aor") -> dict:
    """Normalize a parameter dict: fill defaults, validate ranges, round.

    Particle-wall friction mirrors particle-particle unless given explicitly
    (published wheat sets do this). Per-response protocol knobs join the dict
    so they take part in the hash at behavior-preserving defaults: aor carries
    the Phase-5 fault knobs (lifth/gravz) exactly as before — the "aor"
    canonical is byte-identical to the pre-Phase-9 one, keeping the existing
    cache valid — and drum carries gravz plus rotper/capfric/caproll.
    Returns a new dict with float values rounded to ROUND decimals so two
    numerically-equal requests hash identically.
    """
    if response not in RESPONSES:
        raise ValueError(f"unknown response {response!r} (have {sorted(RESPONSES)})")
    p = {k.lower(): v for k, v in params.items()}
    fric = float(p["fric"])
    rollfric = float(p["rollfric"])
    out = {
        "fric": fric,
        "fricpw": float(p.get("fricpw", fric)),
        "rollfric": rollfric,
        "rollfricpw": float(p.get("rollfricpw", rollfric)),
        "rest": float(p.get("rest", 0.5)),
        "gravz": float(p.get("gravz", -1.0)),
    }
    if response == "aor":
        out["lifth"] = float(p.get("lifth", 0.055))
    elif response == "drum":
        # cover friction defaults: wheat-acrylic (Sugirbay Table 11), a fixed
        # protocol input — the published cover is acrylic regardless of where
        # the wheat-wheat search wanders
        out["rotper"] = float(p.get("rotper", 12.0))
        out["capfric"] = float(p.get("capfric", 0.36))
        out["caproll"] = float(p.get("caproll", 0.29))
    elif response == "drum45":
        # Phase-10 hold-out: at 45 deg the shell material is significant
        # (Sugirbay ANOVA p < 0.001), so the shell pair is a FIXED protocol
        # input at the published wheat-acrylic values, pinned UNCONDITIONALLY —
        # ignore any passed fricpw/rollfricpw. Once Phase-12 made particle-wall
        # friction a routine calibration output (it lands in best.json), honoring
        # it here would let validate.py silently un-pin the published shell and
        # corrupt the hold-out. The shell is not a free knob for this response.
        out["fricpw"] = 0.36
        out["rollfricpw"] = 0.29
        out["rotper"] = float(p.get("rotper", 12.0))
        out["capfric"] = float(p.get("capfric", 0.36))
        out["caproll"] = float(p.get("caproll", 0.29))
        out["tilt"] = float(p.get("tilt", 45.0))
    for key, (lo, hi) in RANGES.items():
        if not lo <= out[key] <= hi:
            raise ValueError(
                f"{key}={out[key]} outside calibration range [{lo}, {hi}]")
    return {k: round(v, ROUND) for k, v in out.items()}


def params_hash(params: dict, response: str = "aor",
                material: dict | None = None) -> str:
    """Stable 10-hex-char digest of the canonical params (cache + TAG key).

    A non-default material extends the blob — its own cache namespace, so a
    changed PSD/density can never collide with stale physics. The default
    material adds NOTHING: every legacy hash is preserved byte-for-byte."""
    canon = canonical(params, response)
    blob = json.dumps(canon, sort_keys=True, separators=(",", ":"))
    mat = material_canon(material)
    if mat is not None:
        blob += "|material:" + json.dumps(
            {k: mat[k] for k in _MAT_HASH_KEYS},
            sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()[:10]


def trial_dir(params: dict, seed: int, response: str = "aor",
              material: dict | None = None) -> Path:
    """results/cache/<prefix><hash>/seed<seed>/ for one (params, seed, response)
    simulation. The aor prefix is "" — the legacy Phase 6-8 layout."""
    prefix = RESPONSES[response]["dir_prefix"]
    return CACHE / f"{prefix}{params_hash(params, response, material)}" / f"seed{seed}"


def _tag(params: dict, seed: int, response: str = "aor",
         material: dict | None = None) -> str:
    """Space-free, filesystem-safe dump prefix. render_trial strips the
    trailing _final/_<step> to recover this, so no '_final'/digit suffixes."""
    prefix = RESPONSES[response]["tag_prefix"]
    return f"{prefix}{params_hash(params, response, material)}_s{seed}"


# ------------------------------------------------------------- one simulation

def _build_argv(canon: dict, seed: int, trial: Path, tag: str,
                response: str = "aor", *, template: Path | None = None) -> list[str]:
    """mpirun command for one run. MESH must be space-free (LIGGGHTS re-tokenizes
    the -var value and the repo root contains a space) -> pass it relative to the
    run cwd, whose path components are all space-free. `template` overrides the
    registry's static .in file (the rendered custom-material variant)."""
    spec = RESPONSES[response]
    mesh_rel = os.path.relpath(spec["mesh"], trial)
    argv = [
        MPIRUN, "-np", str(NRANKS), str(LMP),
        "-in", str(template if template is not None else spec["template"]),
        "-var", "TAG", tag,
        "-var", "MESH", mesh_rel,
        "-var", "FRIC", f"{canon['fric']}",
        "-var", "FRICPW", f"{canon['fricpw']}",
        "-var", "ROLLFRIC", f"{canon['rollfric']}",
        "-var", "ROLLFRICPW", f"{canon['rollfricpw']}",
        "-var", "REST", f"{canon['rest']}",
        "-var", "SEED", str(seed),
        "-var", "GRAVZ", f"{canon['gravz']}",
    ]
    if response == "aor":
        argv += ["-var", "LIFTH", f"{canon['lifth']}"]
    elif response in ("drum", "drum45"):
        caps_rel = os.path.relpath(spec["caps_mesh"], trial)
        argv += ["-var", "CMESH", caps_rel,
                 "-var", "ROTPER", f"{canon['rotper']}",
                 "-var", "CAPFRIC", f"{canon['capfric']}",
                 "-var", "CAPROLL", f"{canon['caproll']}"]
        if response == "drum45":
            argv += ["-var", "TILT", f"{canon['tilt']}"]
    argv += ["-log", f"log.{tag}"]
    return argv


def _launch_sim(canon: dict, seed: int, trial: Path, tag: str,
                response: str = "aor", *, template: Path | None = None,
                wall_limit: int | None = None) -> None:
    """Launch one LIGGGHTS run to completion in `trial`. Raises SimError on a
    nonzero exit or timeout. Factored out so tests can stub the engine.

    stdin=DEVNULL: mpirun otherwise consumes the caller's stdin and stalls a
    batch. start_new_session=True puts mpirun + its ranks in their own process
    group so a timeout kills the whole group, not just the launcher.
    """
    if not LMP.exists():
        raise SimError(f"lmp_auto not found at {LMP} — build it first (Phase 0)")
    if wall_limit is None:
        wall_limit = RESPONSES[response]["wall_limit"]
    argv = _build_argv(canon, seed, trial, tag, response, template=template)
    with open(trial / "run.out", "wb") as out:
        proc = subprocess.Popen(
            argv, cwd=str(trial), stdin=subprocess.DEVNULL,
            stdout=out, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            proc.communicate(timeout=wall_limit)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait()
            raise SimError(f"timeout after {wall_limit}s")
    if proc.returncode != 0:
        raise SimError(f"lmp_auto exited {proc.returncode} (see {trial/'run.out'})")


def _prune(trial: Path, tag: str, response: str = "aor",
           steady_step: int | None = None, settle_step: int | None = None) -> None:
    """Delete every dump except what measure.py needs, keeping each cached
    trial self-contained but compact for overnight batches. aor keeps the
    final + settle frames; drum keeps the final + every steady-state frame
    (the multi-frame measurement must stay reproducible from the pruned dir).
    steady_step/settle_step override the defaults (custom-material DT moves
    both stage boundaries)."""
    post = trial / "post"
    steady = (steady_step if steady_step is not None
              else RESPONSES[response].get("steady_step"))
    settle = settle_step if settle_step is not None else SETTLE_STEP

    def keep(f: Path) -> bool:
        if f.name == f"{tag}_final.liggghts":
            return True
        m = re.search(r"_(\d+)\.liggghts$", f.name)
        if not m or not f.name.startswith(f"{tag}_"):
            return False
        if response == "aor":
            return int(m.group(1)) == settle
        return int(m.group(1)) >= steady

    for f in post.glob("*"):
        if f.suffix in (".liggghts", ".stl") and not keep(f):
            f.unlink()


def _cached(trial: Path, response: str = "aor") -> dict | None:
    """A successful prior result (measured.json with the response's success
    key), else None. A trial with dumps but no valid success JSON (killed
    mid-run) is a miss."""
    mj = trial / "measured.json"
    if not mj.exists():
        return None
    try:
        data = json.loads(mj.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    return data if RESPONSES[response]["success_key"] in data else None


# run_one is split into two halves so the scheduler can parallelize the only
# slow, thread-safe part (the subprocess) while keeping render+measure on the
# main thread — OVITO/Qt state is process-global and segfaults off-main-thread
# (Phase-5 lesson). _simulate is pool-safe; _finish is main-thread only.

def _simulate(canon: dict, seed: int, *, force: bool, response: str = "aor",
              mat: dict | None = None) -> dict:
    """Thread-safe half: cache-check, then launch one LIGGGHTS run. Returns a
    status dict consumed by _finish — never renders or measures here. A custom
    material renders its template variant into the trial dir (jinja, no OVITO,
    pool-safe) and runs under a cost-scaled wall limit."""
    trial = trial_dir(canon, seed, response, mat)
    tag = _tag(canon, seed, response, mat)
    sim = {"seed": seed, "trial": trial, "tag": tag, "response": response}
    if not force:
        hit = _cached(trial, response)
        if hit is not None:
            return {**sim, "status": "cached", "result": hit}
    if trial.exists():                 # clear any stale partial / failed run
        shutil.rmtree(trial)
    (trial / "post").mkdir(parents=True, exist_ok=True)
    try:
        template = _render_template(response, mat, trial) if mat is not None else None
        _launch_sim(canon, seed, trial, tag, response, template=template,
                    wall_limit=_scaled_wall_limit(response, mat))
        return {**sim, "status": "ran"}
    except Exception as err:           # noqa: BLE001 — never crash the batch
        return {**sim, "status": "failed", "error": f"{type(err).__name__}: {err}"}


def _finish(canon: dict, sim: dict, response: str = "aor",
            mat: dict | None = None) -> dict:
    """Main-thread half: render + measure + prune + persist, or pass a cache hit
    / recorded failure straight through. Always returns a result dict and writes
    measured.json (the Phase-6 contract; carries the material so post-hoc tools
    — formation re-sims, audits — can reproduce the exact physics)."""
    if sim["status"] == "cached":
        return sim["result"]
    trial, tag, seed = sim["trial"], sim["tag"], sim["seed"]
    base = {"seed": seed, "params": canon, "tag": tag, "trial_dir": str(trial)}
    if mat is not None:
        base["material"] = mat
    if sim["status"] == "failed":
        result = {**base, "failed": True, "error": sim["error"]}
    else:
        try:
            spec = RESPONSES[response]
            rr = _radius_range(mat)
            if "steady_step" in spec:  # drum family: snapshot + multi-frame measure
                result = render.render_drum_trial(
                    trial, tag=tag,
                    steady_step=_steady_step_for(response, mat),
                    measure_kw=spec.get("measure_kw"),
                    side_view=spec.get("side_view", False),
                    radius_range=rr)
            else:                      # snapshot + measure + audit
                result = render.render_trial(trial, tag=tag, radius_range=rr,
                                             settle_step=_settle_step_for(mat))
            result.update(base)
            _prune(trial, tag, response,
                   steady_step=_steady_step_for(response, mat),
                   settle_step=_settle_step_for(mat))
        except Exception as err:       # noqa: BLE001 — a broken heap must not crash the batch
            result = {**base, "failed": True, "error": f"{type(err).__name__}: {err}"}
    (trial / "measured.json").write_text(json.dumps(result, indent=2))
    return result


def run_one(params: dict, seed: int, *, force: bool = False,
            response: str = "aor", material: dict | None = None) -> dict:
    """Run (or cache-load) one (params, seed) simulation, main-thread. Returns a
    measurement on success (aor_deg, bulk_density_kgm3, ... + seed/params), or
    {"failed": True, "error": ...} on a broken/timed-out/unmeasurable run."""
    canon = canonical(params, response)
    mat = material_canon(material)
    return _finish(canon,
                   _simulate(canon, seed, force=force, response=response, mat=mat),
                   response, mat)


# ------------------------------------------------------------- aggregation

def _aggregate(canon: dict, seeds: list[int], results: list[dict],
               response: str = "aor") -> dict:
    """Average per-seed observables into one candidate result. The aor branch
    is the unchanged Phase-6 output shape; drum returns the drum_aor analog."""
    warnings: list[str] = []
    for r in results:
        warnings.extend(r.get("warnings", []) or [])
        if r.get("failed"):
            warnings.append(f"seed {r.get('seed')} failed: {r.get('error')}")
    common = {
        "n_seeds": len(seeds),
        "seeds": seeds,
        "params": canon,
        "trial_dirs": [r.get("trial_dir") for r in results],
        "warnings": warnings,
    }
    if "steady_step" in RESPONSES[response]:   # drum family
        ok = [r for r in results if r and "drum_aor_deg" in r]
        vals = [r["drum_aor_deg"] for r in ok]
        return {
            "drum_aor": mean(vals) if vals else None,
            "drum_aor_std": pstdev(vals) if len(vals) > 1 else 0.0,
            "drum_frame_std": (
                mean(r["drum_aor_frame_std"] for r in ok) if ok else None),
            "n_ok": len(ok),
            "per_seed": [
                {"seed": r.get("seed"), "drum_aor_deg": r.get("drum_aor_deg"),
                 "drum_aor_frame_std": r.get("drum_aor_frame_std"),
                 "failed": r.get("failed", False)}
                for r in results
            ],
            **common,
        }
    ok = [r for r in results if r and "aor_deg" in r]
    aors = [r["aor_deg"] for r in ok]
    dens = [r["bulk_density_kgm3"] for r in ok if r.get("bulk_density_kgm3") is not None]
    return {
        "aor": mean(aors) if aors else None,
        "bulk_density": mean(dens) if dens else None,
        "aor_std": pstdev(aors) if len(aors) > 1 else 0.0,
        "n_ok": len(ok),
        "per_seed": [
            {"seed": r.get("seed"), "aor_deg": r.get("aor_deg"),
             "bulk_density_kgm3": r.get("bulk_density_kgm3"),
             "failed": r.get("failed", False)}
            for r in results
        ],
        **common,
    }


# ------------------------------------------------------------- scheduler API

def _resolve_jobs(jobs: int | None) -> int:
    """Concurrent simulations. Each is mpirun -np 2, so cap at (cores-2)//2 to
    leave headroom; clamp to [1, 4]. Override via arg or RUNNER_JOBS."""
    if jobs is None:
        env = os.environ.get("RUNNER_JOBS")
        jobs = int(env) if env else max(1, min(4, ((os.cpu_count() or 4) - 2) // 2))
    return max(1, jobs)


def evaluate(params: dict, *, n_seeds: int = 2, jobs: int | None = None,
             force: bool = False, response: str = "aor",
             material: dict | None = None) -> dict:
    """Parameter dict -> averaged observables {"aor", "bulk_density", ...}
    (or {"drum_aor", ...} for response="drum").

    Runs the first n_seeds of SEEDS concurrently, averaging successful seeds.
    Repeated calls return from cache. The headline observable is None only if
    every seed failed. `material` selects the physical inputs (None = wheat).
    """
    canon = canonical(params, response)
    mat = material_canon(material)
    seeds = SEEDS[:n_seeds]
    with ThreadPoolExecutor(max_workers=_resolve_jobs(jobs)) as pool:
        sims = list(pool.map(
            lambda s: _simulate(canon, s, force=force, response=response,
                                mat=mat), seeds))
    results = [_finish(canon, sim, response, mat) for sim in sims]  # main thread
    return _aggregate(canon, seeds, results, response)


def evaluate_batch(param_list: list[dict], *, n_seeds: int = 2,
                   jobs: int | None = None, force: bool = False,
                   response: str = "aor", material: dict | None = None) -> list[dict]:
    """Evaluate many candidates, flattening all (candidate, seed) jobs into one
    shared pool so an overnight LHS screen saturates the machine instead of
    serializing per candidate. Results are regrouped per input candidate."""
    canons = [canonical(p, response) for p in param_list]
    mat = material_canon(material)
    seeds = SEEDS[:n_seeds]
    jobspec = [(i, s) for i in range(len(canons)) for s in seeds]
    with ThreadPoolExecutor(max_workers=_resolve_jobs(jobs)) as pool:
        sims = list(pool.map(
            lambda j: (j[0], _simulate(canons[j[0]], j[1], force=force,
                                       response=response, mat=mat)),
            jobspec))
    by_cand: list[list[dict]] = [[] for _ in canons]
    for idx, sim in sims:                              # render/measure on main thread
        by_cand[idx].append(_finish(canons[idx], sim, response, mat))
    return [_aggregate(canons[i], seeds, by_cand[i], response)
            for i in range(len(canons))]


def evaluate_multi(params: dict, *, responses: tuple[str, ...] = ("aor", "drum"),
                   n_seeds: int = 2, jobs: int | None = None,
                   force: bool = False, material: dict | None = None) -> dict:
    """Evaluate one candidate against several responses at once (Phase 9).

    All (response, seed) simulations flatten into ONE pool — 2 responses x
    2 seeds = 4 independent sims saturate jobs=4 in a single wave — then
    finish serially on the main thread (OVITO constraint). Returns the merged
    per-response aggregates flattened to the top level: aor/aor_std/
    bulk_density from the heap test plus drum_aor/drum_aor_std from the drum,
    with n_ok per response. One response failing leaves the other intact.
    """
    canons = {r: canonical(params, r) for r in responses}
    mat = material_canon(material)
    seeds = SEEDS[:n_seeds]
    jobspec = [(r, s) for r in responses for s in seeds]
    with ThreadPoolExecutor(max_workers=_resolve_jobs(jobs)) as pool:
        sims = list(pool.map(
            lambda j: (j[0], _simulate(canons[j[0]], j[1], force=force,
                                       response=j[0], mat=mat)),
            jobspec))
    by_resp: dict[str, list[dict]] = {r: [] for r in responses}
    for resp, sim in sims:                             # render/measure on main thread
        by_resp[resp].append(_finish(canons[resp], sim, resp, mat))
    aggs = {r: _aggregate(canons[r], seeds, by_resp[r], r) for r in responses}

    merged: dict = {"params": {r: canons[r] for r in responses},
                    "responses": aggs,
                    "n_ok": {r: aggs[r]["n_ok"] for r in responses},
                    "n_seeds": n_seeds,
                    "warnings": [w for r in responses for w in aggs[r]["warnings"]]}
    for r in responses:
        for key in ("aor", "aor_std", "bulk_density", "drum_aor",
                    "drum_aor_std", "drum_frame_std"):
            if key in aggs[r] and key not in merged:
                merged[key] = aggs[r][key]
    return merged


# ------------------------------------------------------------- entry point

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    ev = sub.add_parser("eval", help="evaluate one candidate, print result JSON")
    ev.add_argument("--fric", type=float, required=True)
    ev.add_argument("--rollfric", type=float, required=True)
    ev.add_argument("--rest", type=float, default=0.5)
    ev.add_argument("--fricpw", type=float, help="default: mirror --fric")
    ev.add_argument("--rollfricpw", type=float, help="default: mirror --rollfric")
    ev.add_argument("--lifth", type=float, default=0.055)
    ev.add_argument("--gravz", type=float, default=-1.0, help="1.0 = fault-inject")
    ev.add_argument("--capfric", type=float, default=None,
                    help="drum end-cap friction override (default: the "
                         "canonical wheat-acrylic 0.36 — a 0.0 default here "
                         "silently ran frictionless covers under a wrong hash)")
    ev.add_argument("--caproll", type=float, default=None,
                    help="drum end-cap rolling friction override (default 0.29)")
    ev.add_argument("--tilt", type=float, default=None,
                    help="drum45 axis tilt from horizontal [deg] (default 45)")
    ev.add_argument("--response", choices=[*RESPONSES, "both"], default="aor",
                    help="which simulated test to run (default: aor)")
    ev.add_argument("--seeds", type=int, default=2, help="seeds to average")
    ev.add_argument("--jobs", type=int, help="concurrent sims (default: auto)")
    ev.add_argument("--force", action="store_true", help="ignore cache, rerun")

    args = ap.parse_args()
    if args.cmd == "eval":
        params = {"fric": args.fric, "rollfric": args.rollfric, "rest": args.rest,
                  "lifth": args.lifth, "gravz": args.gravz}
        for opt in ("fricpw", "rollfricpw", "capfric", "caproll", "tilt"):
            val = getattr(args, opt)
            if val is not None:
                params[opt] = val
        if args.response == "both":
            result = evaluate_multi(params, n_seeds=args.seeds, jobs=args.jobs,
                                    force=args.force)
        else:
            result = evaluate(params, n_seeds=args.seeds, jobs=args.jobs,
                              force=args.force, response=args.response)
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
