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
    zero velocities/omegas, type 1, ids 1..n. Returns the path.
    """
    from pathlib import Path

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    n = len(df)
    pad = 0.01
    with open(path, "w") as fh:
        fh.write("ITEM: TIMESTEP\n%d\n" % timestep)
        fh.write("ITEM: NUMBER OF ATOMS\n%d\n" % n)
        fh.write("ITEM: BOX BOUNDS mm mm mm\n")
        for c in ("x", "y", "z"):
            fh.write("%g %g\n" % (df[c].min() - pad, df[c].max() + pad))
        fh.write("ITEM: ATOMS id type x y z vx vy vz "
                 "omegax omegay omegaz radius\n")
        for i, row in enumerate(df.itertuples(index=False), start=1):
            fh.write("%d 1 %.8g %.8g %.8g 0 0 0 0 0 0 %.8g\n"
                     % (i, row.x, row.y, row.z, row.radius))
    return path


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
