#!/usr/bin/env bash
# Phase-5 contact-sheet validation batch: 7 good runs at new (FRIC, ROLLFRIC)
# points (free Phase-7 training data) + 1 deliberately broken run with gravity
# flipped (-var GRAVZ 1.0) that must be visually obvious in the 20-run contact
# sheet. The first good run doubles as the GRAVZ-template-edit regression
# check (AoR must land in the established response range).
#
# The broken run gets a short lift (LIFTH 0.005 -> ~1.3 s total): with
# 'boundary m m m' and no ceiling, flipped gravity sends particles hundreds
# of meters up over the full 6.3 s sim and the shrink-wrapped neighbor grid
# would exhaust memory. ~8 m of flight is plenty broken.
#
# Run from anywhere:  bash results/phase5-contact-sheet/run_batch.sh
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
LMP="$ROOT/external/LIGGGHTS-PUBLIC/src/lmp_auto"
TEMPLATE="$ROOT/templates/aor.in"
# MESH is re-tokenized by the LIGGGHTS input parser (splits on whitespace) —
# must be a space-free path; relative, resolved from each run dir.
MESH="../../../templates/meshes/cylinder_r0.040_h0.100.stl"

REST=0.5

# tag FRIC ROLLFRIC GRAVZ LIFTH SEED
# seeds: 8M..15M-th primes — distinct from the template-internal seeds
# (15485863/15485867/32452843/32452867) and the Phase-4 seeds (3M..7M-th primes)
RUNS="
f30r05      0.30 0.05 -1.0 0.055 141650939
f45r10      0.45 0.10 -1.0 0.055 160481183
f50r12      0.50 0.12 -1.0 0.055 179424673
f55r15      0.55 0.15 -1.0 0.055 198491317
f50r20      0.50 0.20 -1.0 0.055 217645177
f65r10      0.65 0.10 -1.0 0.055 236887691
f70r20      0.70 0.20 -1.0 0.055 256203161
broken_grav 0.40 0.05  1.0 0.005 275604541
"

echo "$RUNS" | while read -r TAG FRIC ROLLFRIC GRAVZ LIFTH SEED; do
  [ -z "$TAG" ] && continue
  dir="$HERE/$TAG"
  if ls "$dir/post/${TAG}_"*.liggghts >/dev/null 2>&1 && [ -f "$dir/DONE" ]; then
    echo "=== $TAG already done, skipping ==="
    continue
  fi
  rm -rf "$dir"; mkdir -p "$dir/post"
  echo "=== $TAG : FRIC=$FRIC ROLLFRIC=$ROLLFRIC GRAVZ=$GRAVZ ==="
  ( cd "$dir" && /usr/bin/time mpirun -np 2 "$LMP" -in "$TEMPLATE" \
      -var TAG "$TAG" -var MESH "$MESH" \
      -var FRIC "$FRIC" -var FRICPW "$FRIC" \
      -var ROLLFRIC "$ROLLFRIC" -var ROLLFRICPW "$ROLLFRIC" \
      -var REST "$REST" -var SEED "$SEED" \
      -var GRAVZ "$GRAVZ" -var LIFTH "$LIFTH" \
      -log "log.$TAG" ) > "$dir/run.out" 2>&1 < /dev/null \
    || echo "!!! $TAG exited nonzero (ok for broken run)"
  # ^ stdin redirected: mpirun otherwise eats the rest of the RUNS list
  touch "$dir/DONE"
  grep -E "AUDIT|inserted 4000" "$dir/run.out" | head -3 || true
done

echo "batch complete"
