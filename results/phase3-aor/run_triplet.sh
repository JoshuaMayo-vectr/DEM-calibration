#!/usr/bin/env bash
# Phase-3 validation triplet: low / med / high friction through templates/aor.in.
# Exit criterion — three visibly different heaps, slope steepening monotonically.
# Run from anywhere:  bash results/phase3-aor/run_triplet.sh
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
LMP="$ROOT/external/LIGGGHTS-PUBLIC/src/lmp_auto"
TEMPLATE="$ROOT/templates/aor.in"
# MESH is passed as a -var and re-tokenized by the LIGGGHTS input parser, which
# splits on whitespace — so it MUST be a space-free path. The repo root contains
# a space, so use a relative path resolved from each run dir (results/phase3-aor/<tag>).
MESH="../../../templates/meshes/cylinder_r0.040_h0.100.stl"

# tag  FRIC  ROLLFRIC
run() {
  local tag=$1 fric=$2 roll=$3
  local dir="$HERE/$tag"
  rm -rf "$dir"; mkdir -p "$dir/post"
  echo "=== $tag : FRIC=$fric ROLLFRIC=$roll ==="
  ( cd "$dir" && /usr/bin/time mpirun -np 2 "$LMP" -in "$TEMPLATE" \
      -var TAG "$tag" -var MESH "$MESH" \
      -var FRIC "$fric" -var FRICPW "$fric" \
      -var ROLLFRIC "$roll" -var ROLLFRICPW "$roll" -var REST 0.5 \
      -log "log.$tag" ) > "$dir/run.out" 2>&1
  grep -E "AUDIT|inserted 4000" "$dir/run.out" | head -3 || true
}

run low  0.20 0.00
run med  0.40 0.05
run high 0.60 0.15

echo "=== crude angles ==="
"$ROOT/.venv/bin/python" "$HERE/crude_angle.py" \
  "$HERE/low/post/low_final.liggghts" \
  "$HERE/med/post/med_final.liggghts" \
  "$HERE/high/post/high_final.liggghts"
