#!/usr/bin/env python3
"""Generate an ASCII STL of an open-ended cylinder (no end caps) for LIGGGHTS mesh walls.

The wall is a single-layer tube of 2*segments triangles with outward-pointing
normals. LIGGGHTS treats mesh walls as two-sided, so the inside face confines
particles regardless of normal direction; normals are still written outward
for clean rendering and downstream tooling.

Phase-1 throwaway that graduates to Phase 3 (parameterized lift cylinder).
"""

import argparse
import math


def cylinder_facets(radius: float, height: float, z0: float, segments: int):
    for i in range(segments):
        a0 = 2.0 * math.pi * i / segments
        a1 = 2.0 * math.pi * (i + 1) / segments
        p00 = (radius * math.cos(a0), radius * math.sin(a0), z0)
        p10 = (radius * math.cos(a1), radius * math.sin(a1), z0)
        p01 = (p00[0], p00[1], z0 + height)
        p11 = (p10[0], p10[1], z0 + height)
        # outward normal of the panel midpoint
        am = (a0 + a1) / 2.0
        n = (math.cos(am), math.sin(am), 0.0)
        # two triangles per panel, counter-clockwise seen from outside
        yield n, (p00, p10, p11)
        yield n, (p00, p11, p01)


def write_stl(path: str, radius: float, height: float, z0: float, segments: int) -> None:
    with open(path, "w") as f:
        f.write("solid cylinder\n")
        for n, tri in cylinder_facets(radius, height, z0, segments):
            f.write(f"  facet normal {n[0]:.6e} {n[1]:.6e} {n[2]:.6e}\n")
            f.write("    outer loop\n")
            for v in tri:
                f.write(f"      vertex {v[0]:.6e} {v[1]:.6e} {v[2]:.6e}\n")
            f.write("    endloop\n")
            f.write("  endfacet\n")
        f.write("endsolid cylinder\n")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--radius", type=float, default=0.05, help="cylinder radius [m]")
    ap.add_argument("--height", type=float, default=0.15, help="cylinder height [m]")
    ap.add_argument("--z0", type=float, default=0.0005, help="bottom edge z [m] (small gap above the floor plane)")
    ap.add_argument("--segments", type=int, default=48, help="circumferential facet pairs")
    ap.add_argument("--out", default="meshes/cylinder.stl", help="output STL path")
    args = ap.parse_args()
    write_stl(args.out, args.radius, args.height, args.z0, args.segments)
    print(f"wrote {args.out}: r={args.radius} h={args.height} z0={args.z0} segments={args.segments}")


if __name__ == "__main__":
    main()
