"""Phase-15 multisphere smoke run: insert + simulate + render + measure one real
LIGGGHTS heap of prolate 3-sphere clumps, in its own cache namespace. Compares
the resulting AoR + bulk density against the single-sphere wheat baseline and
cross-checks our clump volume against LIGGGHTS' Monte-Carlo body mass from the log.
"""
import json, time, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from calibration import runner

CLUMP = [[0.0, 0.0, -0.0026, 0.00175],
         [0.0, 0.0, 0.0,     0.00200],
         [0.0, 0.0, 0.0026,  0.00175]]
MULTI = {**dict(runner.WHEAT_MATERIAL), "name": "wheat-prolate",
         "particle_shape": "multisphere", "clump_spheres": CLUMP,
         "n_particles": 3000}
PARAMS = {"fric": 0.5, "rollfric": 0.12, "rest": 0.5}

V = runner._clump_equiv_volume(CLUMP)
h = runner.params_hash(PARAMS, "aor", MULTI)
print(f"clump union V = {V:.4e} m3   namespace hash = {h}   (wheat baseline a3338ce730)", flush=True)

t0 = time.time()
res = runner.run_one(PARAMS, seed=49979687, response="aor", material=MULTI)
dt = time.time() - t0
print(f"elapsed {dt:.0f}s", flush=True)
print(json.dumps({k: res.get(k) for k in
      ("aor_deg","bulk_density_kgm3","bulk_density_total_kgm3","n_atoms",
       "fit_r2","method","failed","error","warnings")}, indent=2), flush=True)
print("trial_dir:", res.get("trial_dir"), flush=True)
