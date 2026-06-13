"""Synthetic heap generators for testing calibration/measure.py.

Every generator returns a pandas DataFrame with the same columns the dump
parser produces (x, y, z, radius — no velocity columns, so the flier filter
is skipped), built from a seeded numpy Generator so tests are deterministic.
Lengths are SI meters, matching the LIGGGHTS dumps.
"""

import numpy as np
import pandas as pd

PARTICLE_R = 0.00185  # median wheat-sphere radius from the locked PSD


def _to_df(x, y, z, radius):
    return pd.DataFrame({"x": x, "y": y, "z": z, "radius": radius})


def _volume_matched_r_base(angle_deg: float, n: int, particle_r: float,
                           packing: float = 0.58) -> float:
    """Base radius of a cone holding n particles at the given packing
    fraction — mimics the real test, where fixed mass spreads wider as the
    angle shallows (volume conservation)."""
    v_heap = n * (4 / 3) * np.pi * particle_r**3 / packing
    return float((3 * v_heap / (np.pi * np.tan(np.radians(angle_deg)))) ** (1 / 3))


def make_cone(
    angle_deg: float,
    rng: np.random.Generator,
    n: int = 4000,
    r_base: float | None = None,
    particle_r: float = PARTICLE_R,
    jitter: float = 0.5,
) -> pd.DataFrame:
    """Solid cone of particle centers with surface slope angle_deg.

    Centers are sampled uniformly over the cone volume
    z <= (r_base - r) * tan(angle), then jittered by jitter*particle_r
    to mimic packing disorder. r_base defaults to the volume-matched value
    for n particles, like a real fixed-mass heap.
    """
    if r_base is None:
        r_base = _volume_matched_r_base(angle_deg, n, particle_r)
    tan_a = np.tan(np.radians(angle_deg))
    xs, ys, zs = [], [], []
    while sum(len(a) for a in xs) < n:
        m = 4 * n
        x = rng.uniform(-r_base, r_base, m)
        y = rng.uniform(-r_base, r_base, m)
        z = rng.uniform(0.0, r_base * tan_a, m)
        r = np.hypot(x, y)
        keep = z <= (r_base - r) * tan_a
        xs.append(x[keep])
        ys.append(y[keep])
        zs.append(z[keep])
    x = np.concatenate(xs)[:n]
    y = np.concatenate(ys)[:n]
    z = np.concatenate(zs)[:n]
    j = jitter * particle_r
    x = x + rng.uniform(-j, j, n)
    y = y + rng.uniform(-j, j, n)
    z = np.clip(z + rng.uniform(-j, j, n), 0.0, None)
    return _to_df(x, y, z, np.full(n, particle_r))


def make_truncated_cone(
    angle_deg: float,
    rng: np.random.Generator,
    trunc_frac: float = 0.7,
    n: int = 4000,
    r_base: float | None = None,
    particle_r: float = PARTICLE_R,
    jitter: float = 0.5,
) -> pd.DataFrame:
    """Cone with the apex sliced off at trunc_frac of full height (flat plateau)."""
    if r_base is None:
        r_base = _volume_matched_r_base(angle_deg, n, particle_r)
    tan_a = np.tan(np.radians(angle_deg))
    h_cut = trunc_frac * r_base * tan_a
    df = make_cone(angle_deg, rng, n=int(n / max(1e-9, 1 - trunc_frac**3)) + n,
                   r_base=r_base, particle_r=particle_r, jitter=jitter)
    df = df[df["z"] <= h_cut].head(n).reset_index(drop=True)
    return df


def make_flat_disc(
    rng: np.random.Generator,
    n: int = 4000,
    r_disc: float = 0.12,
    height: float = 4 * PARTICLE_R,  # ~2 diameters
    particle_r: float = PARTICLE_R,
) -> pd.DataFrame:
    """Near-flat pancake — the low-friction failure case (true angle ~ 0)."""
    r = r_disc * np.sqrt(rng.uniform(0, 1, n))
    th = rng.uniform(0, 2 * np.pi, n)
    z = rng.uniform(0, height, n)
    return _to_df(r * np.cos(th), r * np.sin(th), z, np.full(n, particle_r))


def make_cone_with_toe(
    angle_deg: float,
    rng: np.random.Generator,
    toe_frac: float = 0.15,
    n: int = 4000,
    r_base: float | None = None,
    particle_r: float = PARTICLE_R,
    jitter: float = 0.5,
) -> pd.DataFrame:
    """Cone whose outer toe_frac of the base blends smoothly into the floor.

    Surface: straight flank of slope tan(angle) that transitions to a
    quadratic toe for r > (1 - toe_frac)*r_base, tangent-matched at the join —
    the shape that makes naive full-profile fits under-read the flank angle.
    """
    if r_base is None:
        r_base = _volume_matched_r_base(angle_deg, n, particle_r)
    tan_a = np.tan(np.radians(angle_deg))
    r_join = (1 - toe_frac) * r_base
    # quadratic z = c*(r_end - r)^2 with slope and value matched at r_join
    # slope: -2c(r_end - r_join) = -tan_a ; value: c(r_end - r_join)^2 = z_join
    z_join = (r_base - r_join) * tan_a
    half_w = 2 * z_join / tan_a  # (r_end - r_join)
    r_end = r_join + half_w
    c = tan_a / (2 * half_w)

    def surf(r):
        z = (r_base - r) * tan_a  # straight flank (apex at r=0)
        toe = c * np.clip(r_end - r, 0, None) ** 2
        return np.where(r <= r_join, z, toe)

    xs, ys, zs = [], [], []
    h_apex = r_base * tan_a
    while sum(len(a) for a in xs) < n:
        m = 4 * n
        x = rng.uniform(-r_end, r_end, m)
        y = rng.uniform(-r_end, r_end, m)
        z = rng.uniform(0.0, h_apex, m)
        keep = z <= surf(np.hypot(x, y))
        xs.append(x[keep])
        ys.append(y[keep])
        zs.append(z[keep])
    x = np.concatenate(xs)[:n]
    y = np.concatenate(ys)[:n]
    z = np.concatenate(zs)[:n]
    j = jitter * particle_r
    x = x + rng.uniform(-j, j, n)
    y = y + rng.uniform(-j, j, n)
    z = np.clip(z + rng.uniform(-j, j, n), 0.0, None)
    return _to_df(x, y, z, np.full(n, particle_r))


def add_outliers(df: pd.DataFrame, rng: np.random.Generator, frac: float = 0.01) -> pd.DataFrame:
    """Scatter frac*N extra particles well above the surface (stray fliers)."""
    n_out = max(1, int(frac * len(df)))
    r_max = np.hypot(df["x"], df["y"]).max()
    z_max = df["z"].max()
    r = r_max * np.sqrt(rng.uniform(0, 1, n_out))
    th = rng.uniform(0, 2 * np.pi, n_out)
    z = rng.uniform(z_max * 1.2, z_max * 2.0, n_out)
    extra = _to_df(r * np.cos(th), r * np.sin(th), z,
                   np.full(n_out, df["radius"].median()))
    return pd.concat([df, extra], ignore_index=True)


def write_dump(df: pd.DataFrame, path, *, timestep: int = 0):
    """Write a synthetic heap as a LIGGGHTS plain-text custom dump.

    Emits the exact format calibration.measure.read_dump parses (and that
    OVITO auto-detects): the standard column set from templates/aor.in, with
    zero velocities/omegas, type 1, ids 1..n. A 'mol' column (Phase-15
    multisphere body id) is emitted right after 'type' when present in df,
    mirroring the template's conditional dump line. Returns the path.
    """
    from pathlib import Path

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    n = len(df)
    pad = 0.01
    has_mol = "mol" in df.columns
    with open(path, "w") as fh:
        fh.write("ITEM: TIMESTEP\n%d\n" % timestep)
        fh.write("ITEM: NUMBER OF ATOMS\n%d\n" % n)
        fh.write("ITEM: BOX BOUNDS mm mm mm\n")
        for c in ("x", "y", "z"):
            fh.write("%g %g\n" % (df[c].min() - pad, df[c].max() + pad))
        fh.write("ITEM: ATOMS id type %sx y z vx vy vz "
                 "omegax omegay omegaz radius\n" % ("mol " if has_mol else ""))
        for i, row in enumerate(df.itertuples(index=False), start=1):
            molstr = ("%d " % int(getattr(row, "mol"))) if has_mol else ""
            fh.write("%d 1 %s%.8g %.8g %.8g 0 0 0 0 0 0 %.8g\n"
                     % (i, molstr, row.x, row.y, row.z, row.radius))
    return path


# ----------------------------------------------------- Phase 15 multisphere
# A prolate 3-sphere wheat clump (body axis = local z): fat center + two
# overlapping end caps, aspect ~2.2 — the Phase-15 representative clump.
WHEAT_CLUMP = [[0.0, 0.0, -0.0026, 0.00175],
               [0.0, 0.0,  0.0000, 0.00200],
               [0.0, 0.0,  0.0026, 0.00175]]


def _random_rotations(n: int, rng: np.random.Generator) -> np.ndarray:
    """n uniformly-random 3×3 rotation matrices (QR of Gaussian matrices, with
    the sign fix so they are proper rotations)."""
    a = rng.standard_normal((n, 3, 3))
    rots = np.empty_like(a)
    for i in range(n):
        q, r = np.linalg.qr(a[i])
        rots[i] = q * np.sign(np.diag(r))
    return rots


def _expand_clumps(cx, cy, cz, clump, rng, *, orient: bool = True) -> pd.DataFrame:
    """Replace each body center (cx,cy,cz) with the clump's sub-spheres, one
    `mol` id per body. orient=True gives each clump a random isotropic
    orientation (a Minkowski dilation of the center cloud — slope-preserving,
    so the heap flank angle is unchanged)."""
    spheres = np.asarray(clump, dtype=float)
    pos, rad = spheres[:, :3], spheres[:, 3]
    nb, k = len(cx), len(spheres)
    cx, cy, cz = np.asarray(cx), np.asarray(cy), np.asarray(cz)
    rots = _random_rotations(nb, rng) if orient else None
    xs = np.empty(nb * k); ys = np.empty(nb * k); zs = np.empty(nb * k)
    rs = np.empty(nb * k); mol = np.empty(nb * k, dtype=int)
    for i in range(nb):
        p = pos @ rots[i].T if orient else pos
        sl = slice(i * k, (i + 1) * k)
        xs[sl], ys[sl], zs[sl] = cx[i] + p[:, 0], cy[i] + p[:, 1], cz[i] + p[:, 2]
        rs[sl], mol[sl] = rad, i + 1
    return pd.DataFrame({"x": xs, "y": ys, "z": zs, "radius": rs, "mol": mol})


def make_multisphere_cone(
    angle_deg: float,
    rng: np.random.Generator,
    n_bodies: int = 1500,
    r_base: float | None = None,
    clump=None,
    orient: bool = True,
) -> pd.DataFrame:
    """Cone of multisphere CLUMPS: body centers form a cone of slope angle_deg
    (volume-matched like make_cone), each expanded into a clump with a shared
    `mol` id. Verifies the measurement reads the heap angle from the sub-sphere
    top cloud — no grouping needed for the angle (the surface IS sub-sphere tops)."""
    clump = WHEAT_CLUMP if clump is None else clump
    r_equiv = float((3 * np.mean([r**3 for *_, r in clump])) ** (1 / 3))
    centers = make_cone(angle_deg, rng, n=n_bodies, r_base=r_base,
                        particle_r=r_equiv, jitter=0.3)
    return _expand_clumps(centers["x"], centers["y"], centers["z"],
                          clump, rng, orient=orient)


def make_packed_multisphere_cylinder(
    packing_frac: float,
    rng: np.random.Generator,
    clump_volume: float,
    cyl_r: float = 0.040,
    h: float = 0.040,
    clump=None,
    orient: bool = True,
) -> pd.DataFrame:
    """Random clumps in a cylinder with body count set so the overlap-corrected
    solid fraction (n_bodies·clump_volume / cyl_volume) equals packing_frac.
    measure_bulk_density(clump_volume_m3=clump_volume) must read packing_frac·ρ;
    the naive sub-sphere-sum path over-reads (it double-counts intra-clump overlap)."""
    clump = WHEAT_CLUMP if clump is None else clump
    n_bodies = int(round(packing_frac * np.pi * cyl_r**2 * h / clump_volume))
    r = cyl_r * np.sqrt(rng.uniform(0, 1, n_bodies))
    th = rng.uniform(0, 2 * np.pi, n_bodies)
    cz = rng.uniform(0, h, n_bodies)
    return _expand_clumps(r * np.cos(th), r * np.sin(th), cz, clump, rng, orient=orient)


def _chord_offset_for_fill(fill_frac: float, drum_r: float) -> float:
    """Signed distance from the drum center to the surface chord such that
    the circular-segment area below it equals fill_frac of the cross-section.
    Bisection (no scipy): fraction below a line at distance d above center is
    1 - [R^2 acos(d/R) - d sqrt(R^2-d^2)] / (pi R^2)."""
    def frac_below(d):
        seg = drum_r**2 * np.arccos(np.clip(d / drum_r, -1, 1)) \
            - d * np.sqrt(max(drum_r**2 - d**2, 0.0))
        return 1.0 - seg / (np.pi * drum_r**2)

    lo, hi = -drum_r, drum_r
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if frac_below(mid) < fill_frac:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def make_drum_bed(
    angle_deg: float,
    rng: np.random.Generator,
    drum_r: float = 0.075,
    length: float = 0.025,
    fill_frac: float = 0.5,
    particle_r: float = PARTICLE_R,
    jitter: float = 0.5,
    s_amp: float = 0.0,
    slope_sign: float = -1.0,
    packing: float = 0.58,
    axial_slope: float = 0.0,
    y_range: tuple[float, float] | None = None,
) -> pd.DataFrame:
    """Drum cross-section bed (axis = y) with a flat surface at angle_deg.

    The bed is the part of the circle x^2 + z^2 <= drum_r^2 below the line
    z = slope_sign*tan(angle)*x + z0, with z0 set by bisection so the
    circular-segment area fraction equals fill_frac. slope_sign=-1 matches
    the template's rotation convention (bed climbs the -x side). s_amp adds
    a cubic end-deviation z += s_amp*(x/drum_r)^3 to emulate the S-shaped
    surface at higher Froude — the chord-window robustness test.
    Particle count follows from fill_frac at the given packing fraction.

    axial_slope (Phase 10, 45-deg inclined drum) tilts the surface along the
    drum axis: z_surf += axial_slope * (y + length/2), so the trace at the
    -y cover (y = -length/2) keeps EXACTLY angle_deg in the x-z plane while
    the surface drops toward +y for axial_slope < 0 — the leaning bed the
    cover-slab measurement targets. axial_slope=0.0 reproduces the original
    generator's RNG call sequence exactly. y_range optionally confines
    centers to a y sub-interval (for composing multi-region test beds).
    """
    s = slope_sign * np.tan(np.radians(angle_deg))
    # offset measured perpendicular to the tilted chord, converted to z
    d_perp = _chord_offset_for_fill(fill_frac, drum_r)
    z0 = d_perp * np.sqrt(1 + s**2)
    v_p = 4 / 3 * np.pi * particle_r**3
    n = int(round(fill_frac * np.pi * drum_r**2 * length * packing / v_p))
    if y_range is None:
        y_range = (-(length / 2 - particle_r), length / 2 - particle_r)

    def surf(x):
        return s * x + z0 + s_amp * (x / drum_r) ** 3

    xs, ys, zs = [], [], []
    if axial_slope == 0.0:
        # legacy path — y independent of (x, z); RNG sequence unchanged
        while sum(len(a) for a in xs) < n:
            m = 4 * n
            x = rng.uniform(-drum_r, drum_r, m)
            z = rng.uniform(-drum_r, drum_r, m)
            keep = (x**2 + z**2 <= (drum_r - particle_r) ** 2) & (z <= surf(x))
            xs.append(x[keep])
            zs.append(z[keep])
            ys.append(rng.uniform(y_range[0], y_range[1], int(keep.sum())))
    else:
        # joint rejection — the surface depends on y
        while sum(len(a) for a in xs) < n:
            m = 6 * n
            x = rng.uniform(-drum_r, drum_r, m)
            z = rng.uniform(-drum_r, drum_r, m)
            y = rng.uniform(y_range[0], y_range[1], m)
            keep = (x**2 + z**2 <= (drum_r - particle_r) ** 2) & (
                z <= surf(x) + axial_slope * (y + length / 2))
            xs.append(x[keep])
            zs.append(z[keep])
            ys.append(y[keep])
    x = np.concatenate(xs)[:n]
    y = np.concatenate(ys)[:n]
    z = np.concatenate(zs)[:n]
    j = jitter * particle_r
    x = x + rng.uniform(-j, j, n)
    z = z + rng.uniform(-j, j, n)
    return _to_df(x, y, z, np.full(n, particle_r))


def write_dump_series(dfs, post_dir, tag: str, steps):
    """Write a list of frames as '<tag>_<step>.liggghts' files (the drum
    steady-state window layout). Returns the list of paths."""
    from pathlib import Path

    post_dir = Path(post_dir)
    return [
        write_dump(df, post_dir / f"{tag}_{step}.liggghts", timestep=step)
        for df, step in zip(dfs, steps)
    ]


def make_packed_cylinder(
    packing_frac: float,
    rng: np.random.Generator,
    cyl_r: float = 0.040,
    h: float = 0.040,
    particle_r: float = PARTICLE_R,
) -> pd.DataFrame:
    """Random centers in a cylinder with particle count set by target packing
    fraction (overlaps allowed — only the volume bookkeeping matters)."""
    v_p = 4 / 3 * np.pi * particle_r**3
    n = int(round(packing_frac * np.pi * cyl_r**2 * h / v_p))
    r = cyl_r * np.sqrt(rng.uniform(0, 1, n))
    th = rng.uniform(0, 2 * np.pi, n)
    z = rng.uniform(0, h, n)
    return _to_df(r * np.cos(th), r * np.sin(th), z, np.full(n, particle_r))
