#!/usr/bin/env python3
"""Crude angle-of-repose estimate from a LIGGGHTS dump — Phase-3 validation only.

NOT the calibration objective. Phase 4 (calibration/measure.py) owns the real,
tested measurement. This is a throwaway flank fit good enough to confirm the
heaps steepen monotonically with friction (the Phase-3 exit criterion).

Method: bin particle centres by radius from the pile axis; take a high z-percentile
in each bin as the free surface; fit a line to the flank (r in [0.3, 0.8] * R_base)
and report atan(-slope) in degrees. Also reports peak height and base radius.

Usage:  python crude_angle.py <dump.liggghts> [more_dumps...]
"""
import sys
import math


def read_dump(path):
    """Return list of (x,y,z) from a LIGGGHTS custom dump (last frame in file)."""
    with open(path) as f:
        lines = f.readlines()
    # find the last "ITEM: ATOMS" block
    idx = max(i for i, l in enumerate(lines) if l.startswith("ITEM: ATOMS"))
    cols = lines[idx].split()[2:]  # column names after "ITEM: ATOMS"
    ix, iy, iz = cols.index("x"), cols.index("y"), cols.index("z")
    pts = []
    for l in lines[idx + 1:]:
        if l.startswith("ITEM:"):
            break
        p = l.split()
        if len(p) < len(cols):
            continue
        pts.append((float(p[ix]), float(p[iy]), float(p[iz])))
    return pts


def angle_of_repose(pts, nbins=24, pct=0.90):
    # pile axis = centroid in x,y
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    rz = [(math.hypot(p[0] - cx, p[1] - cy), p[2]) for p in pts]
    peak = max(z for _, z in rz)
    # use the 95th-percentile radius as the pile edge, ignoring scattered fliers
    radii = sorted(r for r, _ in rz)
    rmax = radii[int(0.95 * (len(radii) - 1))]
    # surface profile: high z-percentile per radial bin
    bins = [[] for _ in range(nbins)]
    for r, z in rz:
        b = min(nbins - 1, int(r / rmax * nbins))
        bins[b].append(z)
    prof = []
    for b in range(nbins):
        if not bins[b]:
            continue
        zs = sorted(bins[b])
        zsurf = zs[min(len(zs) - 1, int(pct * len(zs)))]
        rmid = (b + 0.5) / nbins * rmax
        prof.append((rmid, zsurf))
    # fit flank over r in [0.3, 0.8] * rmax
    flank = [(r, z) for r, z in prof if 0.3 * rmax <= r <= 0.8 * rmax]
    if len(flank) < 2:
        return None, peak, rmax
    n = len(flank)
    sr = sum(r for r, _ in flank)
    sz = sum(z for _, z in flank)
    srz = sum(r * z for r, z in flank)
    srr = sum(r * r for r, _ in flank)
    slope = (n * srz - sr * sz) / (n * srr - sr * sr)
    return math.degrees(math.atan(-slope)), peak, rmax


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    for path in sys.argv[1:]:
        pts = read_dump(path)
        ang, peak, rmax = angle_of_repose(pts)
        a = f"{ang:5.1f} deg" if ang is not None else " n/a "
        print(f"{path}: N={len(pts)}  AoR~{a}  peak={peak*1e3:5.1f} mm  base_r={rmax*1e3:5.1f} mm")


if __name__ == "__main__":
    main()
