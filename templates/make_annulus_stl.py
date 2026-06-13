#!/usr/bin/env python3
"""Generate an ASCII STL of a flat annulus (or full disk) in the x-y plane.

Phase-9 drawdown-probe pieces: the orifice floor (annulus, inner radius =
orifice radius), the removable plug (small disk), and the mass-flow counting
plane (disk below the orifice, never a wall). --inner 0 gives a full disk
(triangle fan); otherwise two triangles per segment span inner -> outer.
Normals point +z; LIGGGHTS mesh walls are two-sided.
"""

import argparse
import math


def annulus_facets(outer: float, inner: float, z: float, segments: int):
    for i in range(segments):
        a0 = 2.0 * math.pi * i / segments
        a1 = 2.0 * math.pi * (i + 1) / segments
        o0 = (outer * math.cos(a0), outer * math.sin(a0), z)
        o1 = (outer * math.cos(a1), outer * math.sin(a1), z)
        n = (0.0, 0.0, 1.0)
        if inner <= 0.0:
            yield n, ((0.0, 0.0, z), o0, o1)
        else:
            i0 = (inner * math.cos(a0), inner * math.sin(a0), z)
            i1 = (inner * math.cos(a1), inner * math.sin(a1), z)
            yield n, (i0, o0, o1)
            yield n, (i0, o1, i1)


def write_stl(path: str, outer: float, inner: float, z: float, segments: int) -> None:
    with open(path, "w") as f:
        f.write("solid annulus\n")
        for n, tri in annulus_facets(outer, inner, z, segments):
            f.write(f"  facet normal {n[0]:.6e} {n[1]:.6e} {n[2]:.6e}\n")
            f.write("    outer loop\n")
            for v in tri:
                f.write(f"      vertex {v[0]:.6e} {v[1]:.6e} {v[2]:.6e}\n")
            f.write("    endloop\n")
            f.write("  endfacet\n")
        f.write("endsolid annulus\n")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--outer", type=float, required=True, help="outer radius [m]")
    ap.add_argument("--inner", type=float, default=0.0,
                    help="inner (orifice) radius [m]; 0 = full disk")
    ap.add_argument("--z", type=float, default=0.0, help="plane height [m]")
    ap.add_argument("--segments", type=int, default=48)
    ap.add_argument("--out", required=True, help="output STL path (space-free)")
    args = ap.parse_args()
    write_stl(args.out, args.outer, args.inner, args.z, args.segments)
    print(f"wrote {args.out}: outer={args.outer} inner={args.inner} z={args.z}")


if __name__ == "__main__":
    main()
