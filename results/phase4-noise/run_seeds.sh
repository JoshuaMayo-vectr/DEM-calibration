#!/usr/bin/env bash
# Phase-4 seed-noise-floor study: 5 insertion seeds at the high parameter set
# (FRIC=0.6 / ROLLFRIC=0.15 — the near-target corner where the optimizer will
# operate). Exit criterion 3: the seed-to-seed angle spread must be below the
# physical sigma of 1.5 deg.
# Run from anywhere:  bash results/phase4-noise/run_seeds.sh
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
LMP="$ROOT/external/LIGGGHTS-PUBLIC/src/lmp_auto"
TEMPLATE="$ROOT/templates/aor.in"
PY="$ROOT/.venv/bin/python"
# MESH is re-tokenized by the LIGGGHTS input parser (splits on whitespace) —
# must be a space-free path; relative, resolved from each run dir.
MESH="../../../templates/meshes/cylinder_r0.040_h0.100.stl"

FRIC=0.6 ROLLFRIC=0.15 REST=0.5
# all distinct from the template-internal seeds 15485863/15485867/32452843/32452867
SEEDS="49979687 67867967 86028121 104395301 122949823"

for SEED in $SEEDS; do
  dir="$HERE/seed_$SEED"
  if [ -f "$dir/post/s${SEED}_final.liggghts" ]; then
    echo "=== seed $SEED already done, skipping ==="
    continue
  fi
  rm -rf "$dir"; mkdir -p "$dir/post"
  echo "=== seed $SEED : FRIC=$FRIC ROLLFRIC=$ROLLFRIC ==="
  ( cd "$dir" && /usr/bin/time mpirun -np 2 "$LMP" -in "$TEMPLATE" \
      -var TAG "s$SEED" -var MESH "$MESH" \
      -var FRIC "$FRIC" -var FRICPW "$FRIC" \
      -var ROLLFRIC "$ROLLFRIC" -var ROLLFRICPW "$ROLLFRIC" \
      -var REST "$REST" -var SEED "$SEED" \
      -log "log.s$SEED" ) > "$dir/run.out" 2>&1
  grep -E "AUDIT|inserted 4000" "$dir/run.out" | head -3 || true
done

echo
echo "| seed | AoR [deg] | sector std | bulk rho [kg/m3] |"
echo "|---|---|---|---|"
for SEED in $SEEDS; do
  "$PY" "$ROOT/calibration/measure.py" \
    "$HERE/seed_$SEED/post/s${SEED}_final.liggghts" \
    --settled "$HERE/seed_$SEED/post/s${SEED}_50000.liggghts" --json \
  | "$PY" -c "import json,sys; d=json.load(sys.stdin); print(f\"| $SEED | {d['aor_deg']:.2f} | {d['aor_sector_std_deg']:.2f} | {d['bulk_density_kgm3']:.0f} |\")"
done
