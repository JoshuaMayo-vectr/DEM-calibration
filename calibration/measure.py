"""Automated heap measurement for DEM calibration (Phase 4).

Reads a LIGGGHTS plain-text custom dump of the settled heap and computes:
  - angle of repose: radially-binned surface profile, line fit on the flank
    only (height window 0.2-0.8 of peak — excludes the rounded tip AND toe
    that made the Phase-3 crude fit under-read);
  - bulk density: interior-slab estimate on the settled-in-cylinder frame.

Every measure_heap() call emits a two-panel audit figure: the profile fit
(left) and an equal-aspect gridded side view for manual angle verification
(right). The optimizer trusts this module blindly — the audit plot and the
synthetic-heap test suite (tests/test_measure.py) are the safety net.

CLI:
    .venv/bin/python calibration/measure.py FINAL_DUMP \
        [--settled SETTLED_DUMP] [--plot PATH] [--json]
"""

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PARTICLE_DENSITY = 1400.0  # kg/m^3, wheat kernel (fixed input, never calibrated)
CYL_RADIUS = 0.040         # m, lifted-cylinder radius from templates/aor.in
DRUM_RADIUS = 0.075        # m, drum inner radius from templates/drum.in (Phase 9)
DRUM_FRAME_DT = 0.2        # s, dump frame spacing from templates/drum.in (DUMPDT)
# audit-plot reference band only — the calibration target lives in optimize.py
DRUM_TARGET_DEG = 36.17
DRUM_TARGET_SIGMA = 3.1

# 45 deg inclined drum — Phase-10 hold-out (Sugirbay 2022 Table 1/2, acrylic
# row; sigma = pooled within-group sqrt(MS_within) = sqrt(8.52), same
# convention as the vertical target's sqrt(9.73)). See experiments/
# ground-truth-wheat-literature.md, "45° inclined drum" section.
DRUM45_TARGET_DEG = 43.65
DRUM45_TARGET_SIGMA = 2.92
# Measurement slab adjacent to the -y cover (the "material side" whose trace
# Sugirbay digitizes at 45 deg): lower bound just outside the cover disk at
# y = -0.0125 so jittered centers aren't clipped; ~2 median diameters deep.
DRUM45_Y_SLAB = (-0.0135, -0.0051)


# ---------------------------------------------------------------- parsing

def read_dump(path: str | Path) -> pd.DataFrame:
    """Parse a LIGGGHTS custom dump; return the LAST frame as a DataFrame.

    Columns come from the 'ITEM: ATOMS ...' header line. Coordinates are in
    SI meters ('units si' in the template; the 'BOX BOUNDS mm mm mm' header
    is boundary flags, not millimeters).
    """
    path = Path(path)
    columns: list[str] = []
    rows: list[list[float]] = []
    with open(path) as fh:
        it = iter(fh)
        for line in it:
            if line.startswith("ITEM: NUMBER OF ATOMS"):
                n_atoms = int(next(it))
            elif line.startswith("ITEM: ATOMS"):
                columns = line.split()[2:]
                rows = [next(it).split() for _ in range(n_atoms)]
    if not rows:
        raise ValueError(f"no ATOMS section found in {path}")
    df = pd.DataFrame(np.array(rows, dtype=float), columns=columns)
    if "type" in df.columns:
        df = df[df["type"] == 1].reset_index(drop=True)
    return df


# ---------------------------------------------------------- surface profile

def _median_diameter(df: pd.DataFrame) -> float:
    return 2.0 * float(df["radius"].median())


def _static_particles(df: pd.DataFrame, speed_max: float) -> pd.DataFrame:
    """Drop moving particles (stray rollers); no-op if velocities absent."""
    if not {"vx", "vy", "vz"}.issubset(df.columns):
        return df
    speed = np.sqrt(df["vx"] ** 2 + df["vy"] ** 2 + df["vz"] ** 2)
    return df[speed <= speed_max].reset_index(drop=True)


def _axis_center(df: pd.DataFrame) -> tuple[float, float]:
    """Mass-weighted (∝ r³) centroid of x, y — the heap axis."""
    w = df["radius"] ** 3
    return float((df["x"] * w).sum() / w.sum()), float((df["y"] * w).sum() / w.sum())


def heap_profile(
    df: pd.DataFrame,
    *,
    bin_width: float | None = None,
    speed_max: float = 0.01,
    min_count: int = 4,
    center: tuple[float, float] | None = None,
) -> pd.DataFrame:
    """Radially-binned free-surface profile.

    Surface height per bin is a flier-robust maximum of particle TOPS
    (z + radius) — the free surface is sphere tops, not centers. Bin width
    defaults to one median particle diameter so resolution follows the
    physics, not the heap size. center overrides the heap-axis estimate
    (needed for azimuthal-sector profiles, where the subset centroid is
    biased off-axis). Returns columns r_mid, z_surf, n.
    """
    df = _static_particles(df, speed_max)
    if bin_width is None:
        bin_width = _median_diameter(df)
    cx, cy = _axis_center(df) if center is None else center
    r = np.hypot(df["x"] - cx, df["y"] - cy).to_numpy()
    top = (df["z"] + df["radius"]).to_numpy()

    d_med = _median_diameter(df)
    n_bins = max(1, int(np.ceil(r.max() / bin_width)))
    idx = np.minimum((r / bin_width).astype(int), n_bins - 1)
    rec = []
    for b in range(n_bins):
        tops = np.sort(top[idx == b])[::-1]
        if len(tops) < min_count:
            continue
        # "supported max": highest top with >= 3 tops within 1.5 diameters
        # below it — rejects isolated fliers hovering above the surface
        need = min(3, len(tops) - 1)
        z_surf = float(np.median(tops))
        for t in tops:
            if ((tops <= t) & (tops > t - 1.5 * d_med)).sum() > need:
                z_surf = float(t)
                break
        rec.append(((b + 0.5) * bin_width, z_surf, len(tops)))
    return pd.DataFrame(rec, columns=["r_mid", "z_surf", "n"])


# ----------------------------------------------------------------- flank fit

def _ols(r: np.ndarray, z: np.ndarray) -> tuple[float, float, float]:
    """Least-squares z = a + b r; returns (slope b, intercept a, r²)."""
    b, a = np.polyfit(r, z, 1)
    pred = a + b * r
    ss_res = float(((z - pred) ** 2).sum())
    ss_tot = float(((z - z.mean()) ** 2).sum())
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 1.0
    return float(b), float(a), r2


def fit_flank(
    profile: pd.DataFrame,
    *,
    window: tuple[float, float] = (0.2, 0.8),
    flat_height_diams: float = 4.0,
    median_diameter: float = 0.0037,
    trim_sigma: float = 2.5,
) -> dict:
    """Fit the heap flank and return the angle of repose.

    Primary method: select profile bins whose surface height lies in
    [window[0], window[1]] * peak height — the published image-analysis
    convention that excludes both the rounded tip and the rounded toe —
    then OLS with one outlier-trimming pass (|residual| > trim_sigma * σ).

    Flat-heap guard: if the peak is below flat_height_diams median
    diameters the height window degenerates to rim noise; fall back to a
    radius window r ∈ [0.2, 0.8] * r_base (method 'radial_window_flat'),
    which returns a continuous near-zero angle for pancake heaps.
    """
    warnings: list[str] = []
    if len(profile) < 2:
        raise ValueError("profile has fewer than 2 bins")
    h_peak = float(profile["z_surf"].max())
    r_base = float(profile["r_mid"].quantile(0.95))

    if h_peak < flat_height_diams * median_diameter:
        method = "radial_window_flat"
        sel = profile[
            (profile["r_mid"] >= 0.2 * r_base) & (profile["r_mid"] <= 0.8 * r_base)
        ]
    else:
        method = "height_window"
        sel = profile[
            (profile["z_surf"] >= window[0] * h_peak)
            & (profile["z_surf"] <= window[1] * h_peak)
        ]

    if len(sel) < 2:  # last resort: fit everything rather than crash
        warnings.append(f"window selected {len(sel)} bins; fit on full profile")
        sel = profile
        method += "+full_profile"

    r = sel["r_mid"].to_numpy()
    z = sel["z_surf"].to_numpy()
    slope, intercept, r2 = _ols(r, z)

    # one trimming pass
    resid = z - (intercept + slope * r)
    sigma = resid.std()
    if sigma > 0:
        keep = np.abs(resid) <= trim_sigma * sigma
        if keep.sum() >= 2 and keep.sum() < len(r):
            r, z = r[keep], z[keep]
            slope, intercept, r2 = _ols(r, z)

    angle = math.degrees(math.atan(-slope))
    if r2 < 0.97 and method == "height_window":
        warnings.append(f"low binned-profile fit quality r²={r2:.3f}")
    if len(r) < 4:
        warnings.append(f"only {len(r)} bins in fit")

    return {
        "angle_deg": angle,
        "slope": slope,
        "intercept": intercept,
        "r2": r2,
        "n_fit": int(len(r)),
        "method": method,
        "h_peak": h_peak,
        "r_base": r_base,
        "fit_r": r,
        "fit_z": z,
        "warnings": warnings,
    }


def _refine_flank_shell(
    r: np.ndarray,
    top: np.ndarray,
    fit: dict,
    *,
    window: tuple[float, float],
    median_diameter: float,
    band_diams: float = 0.75,
    n_iter: int = 3,
) -> dict:
    """Refine the binned flank fit on the raw particle tops.

    The binned profile's extreme-value statistic is biased toward the true
    surface by an amount that shrinks with bin population, which tilts the
    initial fit (sparse apex bins read low). Refinement: OLS over ALL
    particle tops within ±band of the current line — a surface shell of
    constant thickness, so the sampling bias becomes a constant vertical
    offset that cancels in the slope. Iterating walks the band parallel to
    the true surface. Tip/toe stay excluded via the same window applied to
    the line height (or radius window for flat heaps); fliers fall outside
    the band.
    """
    band = band_diams * median_diameter
    slope, intercept = fit["slope"], fit["intercept"]
    r_base = fit["r_base"]
    flat = fit["method"].startswith("radial_window_flat")
    n_sel, r2 = fit["n_fit"], fit["r2"]
    # Window in line height, held FIXED across iterations (per-iteration
    # feedback wanders). Top edge from h_peak — never above a truncation
    # plateau, whose flat surface would pollute the band. Bottom edge from
    # the stage-1 line's extrapolated apex (intercept) — for a plateaued
    # heap h_peak underestimates the apex and 0.2*h_peak would sit in the
    # rounded toe. For a full cone the two coincide.
    z_lo = window[0] * max(fit["h_peak"], intercept)
    z_hi = window[1] * fit["h_peak"]
    for _ in range(n_iter):
        line = intercept + slope * r
        if flat:
            in_window = (r >= 0.2 * r_base) & (r <= 0.8 * r_base)
        else:
            in_window = (line >= z_lo) & (line <= z_hi)
        sel = in_window & (np.abs(top - line) <= band)
        if sel.sum() < 10:
            return fit  # shell degenerate — keep the binned fit
        slope, intercept, r2 = _ols(r[sel], top[sel])
        n_sel = int(sel.sum())
    out = dict(fit)
    out.update(
        angle_deg=math.degrees(math.atan(-slope)),
        slope=slope,
        intercept=intercept,
        r2=r2,
        n_fit=n_sel,
        method=fit["method"] + "+shell",
        fit_r=r[sel],
        fit_z=top[sel],
    )
    return out


def measure_angle(
    df: pd.DataFrame,
    *,
    n_sectors: int = 4,
    bin_width: float | None = None,
    speed_max: float = 0.01,
    window: tuple[float, float] = (0.2, 0.8),
    flat_height_diams: float = 4.0,
) -> dict:
    """Pooled axisymmetric flank fit + per-quadrant fits as a diagnostic.

    Two stages: binned-profile fit for the initial line, then shell
    refinement on the raw particle tops (see _refine_flank_shell). The
    primary angle is the pooled fit (4x the statistics); the sector
    mean/std flags asymmetric or otherwise suspect heaps.
    """
    d_med = _median_diameter(df)
    kw = dict(bin_width=bin_width, speed_max=speed_max)
    profile = heap_profile(df, **kw)
    fit = fit_flank(profile, window=window,
                    flat_height_diams=flat_height_diams, median_diameter=d_med)
    dfp = _static_particles(df, speed_max)
    cxp, cyp = _axis_center(dfp)
    r_all = np.hypot(dfp["x"] - cxp, dfp["y"] - cyp).to_numpy()
    top_all = (dfp["z"] + dfp["radius"]).to_numpy()
    fit = _refine_flank_shell(r_all, top_all, fit, window=window,
                              median_diameter=d_med)

    sector_angles: list[float] = []
    theta = np.arctan2(dfp["y"] - cyp, dfp["x"] - cxp).to_numpy()
    edges = np.linspace(-np.pi, np.pi, n_sectors + 1)
    for i in range(n_sectors):
        # refit the surface shell within the sector, starting from the
        # pooled line — per-sector binning is too sparse to stand alone
        mask = (theta >= edges[i]) & (theta < edges[i + 1])
        try:
            f = _refine_flank_shell(r_all[mask], top_all[mask], fit,
                                    window=window, median_diameter=d_med,
                                    n_iter=2)
            if f is not fit:  # shell degenerate in this sector -> skip
                sector_angles.append(f["angle_deg"])
        except (ValueError, np.linalg.LinAlgError):
            continue

    fit["sector_angles"] = sector_angles
    fit["sector_mean"] = float(np.mean(sector_angles)) if sector_angles else None
    fit["sector_std"] = (
        float(np.std(sector_angles, ddof=1)) if len(sector_angles) > 1 else None
    )
    fit["profile"] = profile
    return fit


# --------------------------------------------------------------- bulk density

def measure_bulk_density(
    df: pd.DataFrame,
    *,
    cyl_radius: float = CYL_RADIUS,
    particle_density: float = PARTICLE_DENSITY,
    speed_max: float = 0.05,
) -> dict:
    """Bulk density of the settled-in-cylinder packing (pre-lift frame).

    Primary estimator: interior slab z ∈ [2d, h_fill - 2d] (d = median
    diameter), which excludes the loose free surface and the floor-ordered
    layer; centers-in-slab counting cancels sphere-crossing edge effects to
    first order. Cross-check: total mass over total filled volume.
    """
    warnings: list[str] = []
    df = _static_particles(df, speed_max)
    r_xy = np.hypot(df["x"], df["y"])
    if (r_xy > cyl_radius * 1.05).any():
        warnings.append(
            "particles outside cylinder radius — is this really the settled "
            "(pre-lift) frame?"
        )
    d = _median_diameter(df)
    tops = df["z"] + df["radius"]
    h_fill = float(tops.quantile(0.99))
    mass = particle_density * (4 / 3) * np.pi * df["radius"] ** 3
    area = np.pi * cyl_radius**2

    z_lo, z_hi = 2 * d, h_fill - 2 * d
    rho_slab = None
    if z_hi - z_lo >= d:
        in_slab = (df["z"] >= z_lo) & (df["z"] <= z_hi)
        rho_slab = float(mass[in_slab].sum() / (area * (z_hi - z_lo)))
    else:
        warnings.append("bed too shallow for interior slab; using total only")

    rho_total = float(mass.sum() / (area * h_fill))
    # slab runs ~5-8% above total systematically (total includes the loose
    # free surface) — only flag disagreement beyond that
    if rho_slab is not None and abs(rho_slab - rho_total) / rho_total > 0.12:
        warnings.append(
            f"slab ({rho_slab:.0f}) vs total ({rho_total:.0f}) densities "
            "disagree > 12%"
        )
    return {
        "bulk_density_kgm3": rho_slab if rho_slab is not None else rho_total,
        "bulk_density_total_kgm3": rho_total,
        "fill_height_m": h_fill,
        "warnings": warnings,
    }


# ----------------------------------------------------------------- audit plot

def plot_profile_fit(
    df: pd.DataFrame,
    fit: dict,
    out_path: str | Path,
    *,
    title: str = "",
    speed_max: float = 0.01,
) -> None:
    """Two-panel audit figure.

    Left: r-z particle cloud + binned surface + highlighted fit window +
    fitted flank line, annotated. Right: equal-aspect x-z side projection
    with 10 mm gridlines and the mirrored flank line — a human can measure
    rise/run off the grid and compare with the printed angle (the Phase-4
    manual-agreement check).
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    profile = fit["profile"]
    dfs = _static_particles(df, speed_max)
    cx, cy = _axis_center(dfs)
    r_all = np.hypot(dfs["x"] - cx, dfs["y"] - cy)
    top_all = dfs["z"] + dfs["radius"]

    fig, (ax1, ax2) = plt.subplots(
        1, 2, figsize=(13, 5.5), gridspec_kw={"width_ratios": [1, 1.2]}
    )

    # --- left: quantitative profile fit
    ax1.scatter(r_all * 1e3, top_all * 1e3, s=2, c="0.8", label="particle tops")
    ax1.plot(profile["r_mid"] * 1e3, profile["z_surf"] * 1e3, "o", ms=4,
             c="tab:blue", label="bin surface")
    ax1.plot(fit["fit_r"] * 1e3, fit["fit_z"] * 1e3, "o", ms=6, mfc="none",
             c="tab:red", label="fit window")
    rr = np.array([0.0, fit["r_base"] * 1.05])
    ax1.plot(rr * 1e3, (fit["intercept"] + fit["slope"] * rr) * 1e3, "-",
             c="tab:red", lw=1.5, label="flank fit")
    sect = (
        f"sectors {fit['sector_mean']:.1f}±{fit['sector_std']:.1f}°"
        if fit.get("sector_std") is not None
        else ""
    )
    ax1.set_title(
        f"AoR = {fit['angle_deg']:.2f}°  (r²={fit['r2']:.3f}, n={fit['n_fit']}, "
        f"{fit['method']})  {sect}"
    )
    ax1.set_xlabel("r  [mm]")
    ax1.set_ylabel("z  [mm]")
    ax1.set_ylim(bottom=0)
    ax1.legend(loc="upper right", fontsize=8)

    # --- right: manual-check side view
    ax2.scatter(dfs["x"] * 1e3, (dfs["z"] + dfs["radius"]) * 1e3, s=2, c="0.6")
    for sgn in (+1, -1):
        rr = np.array([0.0, fit["r_base"]])
        ax2.plot((cx + sgn * rr) * 1e3,
                 (fit["intercept"] + fit["slope"] * rr) * 1e3,
                 "-", c="tab:red", lw=1.2)
    ax2.set_aspect("equal")
    ax2.xaxis.set_major_locator(plt.MultipleLocator(10))
    ax2.yaxis.set_major_locator(plt.MultipleLocator(10))
    ax2.grid(True, which="major", lw=0.4, alpha=0.6)
    ax2.set_ylim(bottom=0)
    ax2.set_xlabel("x  [mm]   (grid = 10 mm — measure rise/run to verify)")
    ax2.set_ylabel("z  [mm]")
    ax2.set_title(f"side view — automated angle {fit['angle_deg']:.2f}°")

    if title:
        fig.suptitle(title)
    fig.tight_layout()
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=140)
    plt.close(fig)


# ------------------------------------------------- drum dynamic AoR (Phase 9)

def _frame_step(path: str | Path) -> int:
    """Numeric timestep from a '<tag>_<step>.liggghts' dump filename."""
    stem = Path(path).stem
    tail = stem.rsplit("_", 1)[-1]
    return int(tail) if tail.isdigit() else -1


def drum_surface_profile(
    df: pd.DataFrame,
    *,
    bin_width: float | None = None,
    min_count: int = 4,
) -> pd.DataFrame:
    """x-binned free-surface profile of the drum bed (cross-section view).

    The drum axis is y (templates/drum.in), so the flowing surface lives in
    the x-z plane. Same supported-max-of-particle-tops statistic as
    heap_profile, binned along x instead of radius. NO static-particle
    filter — the bed is deliberately flowing. Returns x_mid, z_surf, n.
    """
    if bin_width is None:
        bin_width = _median_diameter(df)
    x = df["x"].to_numpy()
    top = (df["z"] + df["radius"]).to_numpy()
    d_med = _median_diameter(df)

    x0 = x.min()
    n_bins = max(1, int(np.ceil((x.max() - x0) / bin_width)))
    idx = np.minimum(((x - x0) / bin_width).astype(int), n_bins - 1)
    rec = []
    for b in range(n_bins):
        tops = np.sort(top[idx == b])[::-1]
        if len(tops) < min_count:
            continue
        need = min(3, len(tops) - 1)
        z_surf = float(np.median(tops))
        for t in tops:
            if ((tops <= t) & (tops > t - 1.5 * d_med)).sum() > need:
                z_surf = float(t)
                break
        rec.append((x0 + (b + 0.5) * bin_width, z_surf, len(tops)))
    return pd.DataFrame(rec, columns=["x_mid", "z_surf", "n"])


def measure_drum_frame(
    df: pd.DataFrame,
    *,
    chord_window: tuple[float, float] = (0.2, 0.8),
    bin_width: float | None = None,
    trim_sigma: float = 2.5,
    y_slab: tuple[float, float] | None = None,
) -> dict:
    """Surface-line fit on ONE drum frame; returns signed slope + |angle|.

    Fit window: bins whose x lies in the central chord_window fraction of
    the occupied chord — the S-curve defense: the surface kinks live in the
    outer ~20% where it meets the drum wall. One outlier-trimming pass like
    fit_flank. The slope keeps its sign (rotation-direction check upstream);
    angle_deg is the unsigned inclination.

    y_slab (Phase 10, inclined drum): restrict the fit to particles with
    y_slab[0] <= y <= y_slab[1] — the cover-adjacent slab. At 45 deg the
    free surface is not y-uniform (bed deepest at the lower cover), so a
    whole-bed fit smears the trace; within a ~2-diameter slab the axial
    height variation is approximately constant in x and cancels in the
    slope (the same argument as the Phase-4 shell-refinement bias). The
    slab IS the published measurement: Sugirbay digitizes the trace
    adjacent to the material side, seen by a camera concentric with the
    drum axis — our x-z coordinates in the gravity-tilted drum frame.
    """
    warnings: list[str] = []
    if y_slab is not None:
        n_total = len(df)
        df = df[(df["y"] >= y_slab[0]) & (df["y"] <= y_slab[1])]
        if len(df) < 300:
            warnings.append(
                f"y-slab holds only {len(df)} of {n_total} particles — "
                "slab fit sparse"
            )
    profile = drum_surface_profile(df, bin_width=bin_width)
    if len(profile) < 4:
        raise ValueError(f"drum profile has only {len(profile)} bins")
    x_lo = float(profile["x_mid"].min())
    span = float(profile["x_mid"].max()) - x_lo
    sel = profile[
        (profile["x_mid"] >= x_lo + chord_window[0] * span)
        & (profile["x_mid"] <= x_lo + chord_window[1] * span)
    ]
    if len(sel) < 4:
        warnings.append(f"chord window selected {len(sel)} bins; fit on full profile")
        sel = profile

    x = sel["x_mid"].to_numpy()
    z = sel["z_surf"].to_numpy()
    slope, intercept, r2 = _ols(x, z)
    resid = z - (intercept + slope * x)
    sigma = resid.std()
    if sigma > 0:
        keep = np.abs(resid) <= trim_sigma * sigma
        if keep.sum() >= 4 and keep.sum() < len(x):
            x, z = x[keep], z[keep]
            slope, intercept, r2 = _ols(x, z)

    # shell refinement on the raw particle tops — the binned extreme-value
    # statistic carries the same population-dependent ~0.8 deg bias Phase 4
    # found on heaps; a constant-thickness shell around the line turns it
    # into a constant offset that cancels in the slope (cf.
    # _refine_flank_shell, which this mirrors for the chord geometry).
    d_med = _median_diameter(df)
    x_all = df["x"].to_numpy()
    top_all = (df["z"] + df["radius"]).to_numpy()
    in_window = (x_all >= x_lo + chord_window[0] * span) & (
        x_all <= x_lo + chord_window[1] * span)
    band = 0.75 * d_med
    fit_x, fit_z, n_fit = x, z, int(len(x))
    for _ in range(3):
        line = intercept + slope * x_all
        shell = in_window & (np.abs(top_all - line) <= band)
        if shell.sum() < 10:
            break  # shell degenerate — keep the binned fit
        slope, intercept, r2 = _ols(x_all[shell], top_all[shell])
        fit_x, fit_z, n_fit = x_all[shell], top_all[shell], int(shell.sum())

    if r2 < 0.95:
        warnings.append(f"low surface-fit quality r²={r2:.3f}")
    return {
        "angle_deg": math.degrees(math.atan(abs(slope))),
        "slope": float(slope),
        "intercept": float(intercept),
        "r2": r2,
        "n_fit": n_fit,
        "fit_x": fit_x,
        "fit_z": fit_z,
        "profile": profile,
        "warnings": warnings,
    }


def measure_drum(
    frame_paths: list[str | Path],
    *,
    plot_path: str | Path | None = None,
    expected_slope_sign: float = -1.0,
    frame_dt: float = DRUM_FRAME_DT,
    y_slab: tuple[float, float] | None = None,
    target: float = DRUM_TARGET_DEG,
    target_sigma: float = DRUM_TARGET_SIGMA,
    **kw,
) -> dict:
    """Dynamic angle of repose from the steady-state drum frames.

    Per-frame surface-line fits averaged over the window — the multi-frame
    mean beats the avalanche fluctuation that a single frame carries.
    Guards: (a) steadiness — OLS drift of angle vs time across the window
    > 1 deg flags an unfinished spin-up; (b) rotation sign — the mean slope
    must match the template's rotation direction (dz/dx < 0 for positive
    ROTPER), catching a backwards mesh rotation; (c) lean — with a y_slab
    (inclined drum) the bed must actually rest against the measured cover,
    catching a wrong tilt sign. Returns a flat JSON-serializable dict (the
    drum analog of measure_heap). target/target_sigma only label the audit
    plot's band (36.17 ± 3.1 vertical, 43.65 ± 2.92 at 45 deg).
    """
    paths = sorted(frame_paths, key=_frame_step)
    if not paths:
        raise ValueError("no drum frames given")
    warnings: list[str] = []
    fits, angles, slopes = [], [], []
    for p in paths:
        df = read_dump(p)
        f = measure_drum_frame(df, y_slab=y_slab, **kw)
        fits.append((p, df, f))
        angles.append(f["angle_deg"])
        slopes.append(f["slope"])
        for w in f["warnings"]:
            warnings.append(f"{Path(p).name}: {w}")

    if y_slab is not None:
        slab_side = math.copysign(1.0, (y_slab[0] + y_slab[1]) / 2.0)
        y_mean = float(fits[-1][1]["y"].mean())
        if y_mean * slab_side <= 0:  # leaning away from the measured cover
            warnings.append(
                "bed not leaning on the measured cover — check tilt sign"
            )

    ang = np.array(angles)
    n = len(ang)
    mean = float(ang.mean())
    std = float(ang.std(ddof=1)) if n > 1 else 0.0

    trend = 0.0
    if n > 2:
        t = np.arange(n) * frame_dt
        b, b0, _ = _ols(t, ang)
        trend = float(b * t[-1])  # total drift across the window [deg]
        # noise-aware steadiness: flag drift that is both material (> 1 deg)
        # AND significant against the frame noise (> 2 se). Intermittent
        # flows (the 45-deg cover slab avalanches with ~2.5 deg frame
        # spread) otherwise trip the guard on cycle phase at steady state.
        resid = ang - (b0 + b * t)
        denom = float(((t - t.mean()) ** 2).sum())
        se_trend = (math.sqrt(float((resid ** 2).sum()) / (n - 2) / denom)
                    * t[-1] if denom > 0 else 0.0)
        if abs(trend) > 1.0 and abs(trend) > 2.0 * se_trend:
            warnings.append(
                f"angle drifts {trend:+.1f} deg across the window "
                f"(2se {2 * se_trend:.1f}) — drum not steady, extend SPINUP"
            )
    if std > 3.0:
        warnings.append(f"frame-to-frame spread {std:.1f} deg > 3 deg")
    mean_slope = float(np.mean(slopes))
    if mean_slope * expected_slope_sign < 0:
        warnings.append(
            "surface slope sign opposite to the rotation direction — "
            "check the mesh rotation"
        )

    result = {
        "drum_aor_deg": mean,
        "drum_aor_frame_std": std,
        "drum_aor_se": std / math.sqrt(n) if n > 1 else None,
        "n_frames": n,
        "frame_angles": [float(a) for a in angles],
        "drum_trend_deg": trend,
        "fit_r2_median": float(np.median([f["r2"] for _, _, f in fits])),
        "n_atoms": int(len(fits[-1][1])),
        "warnings": warnings,
        "plot_path": None,
    }
    if plot_path is not None:
        plot_drum_fit(fits, result, plot_path, frame_dt=frame_dt,
                      target=target, target_sigma=target_sigma)
        result["plot_path"] = str(plot_path)
    return result


def plot_drum_fit(
    fits: list,
    result: dict,
    out_path: str | Path,
    *,
    title: str = "",
    frame_dt: float = DRUM_FRAME_DT,
    target: float = DRUM_TARGET_DEG,
    target_sigma: float = DRUM_TARGET_SIGMA,
) -> None:
    """Two-panel drum audit figure (the analog of plot_profile_fit).

    Left: representative mid-window frame — x-z particle tops, bin surface,
    fit window, fitted line, drum outline. Right: per-frame angle vs time
    with the mean ± std band and the literature target band, so a human can
    eyeball steadiness and target proximity in one glance.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    path, df, fit = fits[len(fits) // 2]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5.5))

    # --- left: representative frame
    tops = df["z"] + df["radius"]
    ax1.scatter(df["x"] * 1e3, tops * 1e3, s=2, c="0.8", label="particle tops")
    prof = fit["profile"]
    ax1.plot(prof["x_mid"] * 1e3, prof["z_surf"] * 1e3, "o", ms=4,
             c="tab:blue", label="bin surface")
    ax1.plot(fit["fit_x"] * 1e3, fit["fit_z"] * 1e3, "o", ms=6, mfc="none",
             c="tab:red", label="fit window")
    xx = np.array([fit["fit_x"].min() * 1.3, fit["fit_x"].max() * 1.3])
    ax1.plot(xx * 1e3, (fit["intercept"] + fit["slope"] * xx) * 1e3, "-",
             c="tab:red", lw=1.5, label="surface fit")
    th = np.linspace(0, 2 * np.pi, 200)
    ax1.plot(DRUM_RADIUS * np.cos(th) * 1e3, DRUM_RADIUS * np.sin(th) * 1e3,
             "-", c="0.5", lw=0.8, label="drum shell")
    ax1.set_aspect("equal")
    ax1.set_xlabel("x  [mm]")
    ax1.set_ylabel("z  [mm]")
    ax1.set_title(
        f"frame {Path(path).name}: {fit['angle_deg']:.2f}°  "
        f"(r²={fit['r2']:.3f}, n={fit['n_fit']})"
    )
    ax1.legend(loc="upper right", fontsize=8)

    # --- right: angle vs time across the window
    ang = np.array(result["frame_angles"])
    t = np.arange(len(ang)) * frame_dt
    mean, std = result["drum_aor_deg"], result["drum_aor_frame_std"]
    ax2.axhspan(target - target_sigma, target + target_sigma,
                color="tab:green", alpha=0.15,
                label=f"target {target} ± {target_sigma}°")
    ax2.axhspan(mean - std, mean + std, color="tab:red", alpha=0.15)
    ax2.axhline(mean, c="tab:red", lw=1.2,
                label=f"mean {mean:.2f} ± {std:.2f}°")
    ax2.plot(t, ang, "o-", ms=4, c="tab:blue", lw=0.8, label="per-frame angle")
    ax2.set_xlabel("time in measurement window  [s]")
    ax2.set_ylabel("dynamic AoR  [deg]")
    ax2.set_title(
        f"dynamic AoR = {mean:.2f}°  (n={len(ang)} frames, "
        f"drift {result['drum_trend_deg']:+.2f}°)"
    )
    ax2.legend(loc="best", fontsize=8)

    if title:
        fig.suptitle(title)
    fig.tight_layout()
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=140)
    plt.close(fig)


# ------------------------------------------- drawdown flow rate (Phase 9 probe)

def measure_drawdown(log_path: str | Path, *, dt: float = 8.0e-6,
                     window: tuple[float, float] = (0.2, 0.8),
                     plot_path: str | Path | None = None) -> dict:
    """Orifice mass-flow rate from a drawdown log's thermo series.

    Parses (step, f_ms[1]) — cumulative crossed mass from fix massflow/mesh —
    out of every thermo block in the LIGGGHTS log, then fits an OLS slope to
    mass vs time over the central window of the discharged mass (excludes the
    plug-opening transient and the end-of-drain tail). Returns a flat dict:
    flow_rate_kgs, fit r², the window, total crossed mass.
    """
    rows: list[tuple[int, float]] = []
    cols: list[str] | None = None
    with open(log_path, errors="ignore") as fh:
        for line in fh:
            parts = line.split()
            if not parts:
                continue
            if parts[0] == "Step":
                cols = parts  # LIGGGHTS strips the f_ prefix: 'ms[1]'
                ms_col = next((i for i, c in enumerate(cols)
                               if c.endswith("ms[1]")), None)
                continue
            if cols and ms_col is not None and len(parts) == len(cols):
                try:
                    rows.append((int(parts[0]), float(parts[ms_col])))
                except (ValueError, IndexError):
                    cols = None  # left the thermo block
    if len(rows) < 10:
        raise ValueError(f"only {len(rows)} thermo rows parsed from {log_path}")

    steps = np.array([r[0] for r in rows], dtype=float)
    mass = np.array([r[1] for r in rows])
    m_final = float(mass.max())
    warnings: list[str] = []
    if m_final <= 0:
        return {"flow_rate_kgs": 0.0, "fit_r2": None, "crossed_mass_kg": 0.0,
                "n_rows": len(rows), "warnings": ["no mass crossed the outlet"],
                "plot_path": None}

    lo, hi = window[0] * m_final, window[1] * m_final
    sel = (mass >= lo) & (mass <= hi)
    if sel.sum() < 5:
        warnings.append(f"window holds {int(sel.sum())} rows; fit on all flowing rows")
        sel = mass > 0
    t = steps[sel] * dt
    slope, intercept, r2 = _ols(t, mass[sel])
    if r2 < 0.99:
        warnings.append(f"flow not steady: mass-vs-t r²={r2:.4f} (arching?)")

    result = {
        "flow_rate_kgs": float(slope),
        "fit_r2": r2,
        "fit_window_s": [float(t.min()), float(t.max())],
        "crossed_mass_kg": m_final,
        "n_rows": len(rows),
        "warnings": warnings,
        "plot_path": None,
    }
    if plot_path is not None:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(7, 5))
        ax.plot(steps * dt, mass * 1e3, ".", ms=2, c="0.6", label="crossed mass")
        tt = np.array([t.min(), t.max()])
        ax.plot(tt, (intercept + slope * tt) * 1e3, "-", c="tab:red",
                label=f"fit {slope*1e3:.1f} g/s (r²={r2:.4f})")
        ax.set_xlabel("time [s]")
        ax.set_ylabel("discharged mass [g]")
        ax.set_title(f"drawdown flow rate = {slope*1e3:.1f} g/s")
        ax.legend()
        fig.tight_layout()
        plot_path = Path(plot_path)
        plot_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(plot_path, dpi=140)
        plt.close(fig)
        result["plot_path"] = str(plot_path)
    return result


# -------------------------------------------------------------- entry point

def measure_heap(
    final_dump: str | Path,
    settled_dump: str | Path | None = None,
    plot_path: str | Path | None = None,
    **kw,
) -> dict:
    """Measure one trial: angle of repose (+ audit plot, always) and, if the
    settled pre-lift dump is given, bulk density. This is the function the
    Phase-6 runner calls. Returns a flat JSON-serializable dict.
    """
    final_dump = Path(final_dump)
    df = read_dump(final_dump)
    fit = measure_angle(df, **kw)

    if plot_path is None:
        plot_path = final_dump.parent / f"{final_dump.stem}_profilefit.png"
    plot_profile_fit(df, fit, plot_path, title=final_dump.name)

    result = {
        "aor_deg": fit["angle_deg"],
        "aor_sector_mean_deg": fit["sector_mean"],
        "aor_sector_std_deg": fit["sector_std"],
        "fit_r2": fit["r2"],
        "fit_n_bins": fit["n_fit"],
        "method": fit["method"],
        "peak_height_m": fit["h_peak"],
        "base_radius_m": fit["r_base"],
        "bulk_density_kgm3": None,
        "bulk_density_total_kgm3": None,
        "fill_height_m": None,
        "n_atoms": int(len(df)),
        "warnings": list(fit["warnings"]),
        "plot_path": str(plot_path),
    }
    if settled_dump is not None:
        dens = measure_bulk_density(read_dump(settled_dump))
        result["bulk_density_kgm3"] = dens["bulk_density_kgm3"]
        result["bulk_density_total_kgm3"] = dens["bulk_density_total_kgm3"]
        result["fill_height_m"] = dens["fill_height_m"]
        result["warnings"] += dens["warnings"]
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("final_dump", nargs="+",
                    help="final-state dump file (heap) or steady-state frame "
                         "series (--drum)")
    ap.add_argument("--drum", action="store_true",
                    help="drum mode: positionals are the steady-state frames")
    ap.add_argument("--settled", help="settled pre-lift dump (for bulk density)")
    ap.add_argument("--plot", help="audit-plot path (default: alongside dump)")
    ap.add_argument("--json", action="store_true", help="print result as JSON")
    args = ap.parse_args()

    if args.drum:
        plot = args.plot or (Path(args.final_dump[0]).parent / "drum_fit.png")
        result = measure_drum(args.final_dump, plot_path=plot)
        result.pop("frame_angles", None)  # keep CLI output scannable
    else:
        result = measure_heap(args.final_dump[0], settled_dump=args.settled,
                              plot_path=args.plot)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        for k, v in result.items():
            print(f"{k:28s} {v}")
    if result["warnings"]:
        print("WARNINGS:", "; ".join(result["warnings"]), file=sys.stderr)


if __name__ == "__main__":
    main()
