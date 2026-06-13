#!/usr/bin/env python3
"""Generate an ASCII STL of an open-ended drum shell (cylinder about the y-axis).

Sibling of make_cylinder_stl.py (z-axis lift cylinder): same single-layer tube
of 2*segments triangles with outward normals, but the axis runs along y and the
tube is centered on the origin — the Phase-9 rotating drum spins about y via
fix move/mesh ... rotate origin 0. 0. 0. axis 0. 1. 0. End confinement is NOT
part of this mesh: the drum ends are frictionless primitive y-plane walls
(quasi-2D idealization, see experiments/ground-truth-wheat-literature.md).
"""

import argparse
import math


def drum_facets(radius: float, length: float, segments: int,
                caps: bool = False, caps_only: bool = False):
    y0, y1 = -length / 2.0, length / 2.0
    for i in range(segments):
        a0 = 2.0 * math.pi * i / segments
        a1 = 2.0 * math.pi * (i + 1) / segments
        # circle lives in the x-z plane; axis along y
        p00 = (radius * math.cos(a0), y0, radius * math.sin(a0))
        p10 = (radius * math.cos(a1), y0, radius * math.sin(a1))
        p01 = (p00[0], y1, p00[2])
        p11 = (p10[0], y1, p10[2])
        if not caps_only:
            am = (a0 + a1) / 2.0
            n = (math.cos(am), 0.0, math.sin(am))
            yield n, (p00, p11, p10)
            yield n, (p00, p01, p11)
        if caps or caps_only:
            # end disks as triangle fans about the axis — co-rotating covers
            # (the published protocol's acrylic cover rotates WITH the drum;
            # a static frictional cap locks the bed instead). caps_only emits
            # the disks as their OWN mesh so the cover gets its own atom type
            # and friction pair (wheat-acrylic), independent of the shell.
            c0, c1 = (0.0, y0, 0.0), (0.0, y1, 0.0)
            yield (0.0, -1.0, 0.0), (c0, p10, p00)
            yield (0.0, +1.0, 0.0), (c1, p01, p11)


def write_stl(path: str, radius: float, length: float, segments: int,
              caps: bool = False, caps_only: bool = False) -> None:
    with open(path, "w") as f:
        f.write("solid drum\n")
        for n, tri in drum_facets(radius, length, segments, caps, caps_only):
            f.write(f"  facet normal {n[0]:.6e} {n[1]:.6e} {n[2]:.6e}\n")
            f.write("    outer loop\n")
            for v in tri:
                f.write(f"      vertex {v[0]:.6e} {v[1]:.6e} {v[2]:.6e}\n")
            f.write("    endloop\n")
            f.write("  endfacet\n")
        f.write("endsolid drum\n")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--radius", type=float, default=0.075, help="drum inner radius [m]")
    ap.add_argument("--length", type=float, default=0.025, help="drum axial length [m] (centered on y=0)")
    ap.add_argument("--segments", type=int, default=48, help="circumferential facet pairs")
    ap.add_argument("--caps", action="store_true",
                    help="add co-rotating end disks (the published acrylic cover)")
    ap.add_argument("--caps-only", action="store_true",
                    help="emit ONLY the end disks (separate cover mesh, own atom type)")
    ap.add_argument("--out", default="meshes/drum.stl", help="output STL path (must be space-free for -var MESH)")
    args = ap.parse_args()
    write_stl(args.out, args.radius, args.length, args.segments,
              caps=args.caps, caps_only=args.caps_only)
    print(f"wrote {args.out}: r={args.radius} l={args.length} segments={args.segments} "
          f"caps={args.caps} caps_only={args.caps_only}")


if __name__ == "__main__":
    main()
