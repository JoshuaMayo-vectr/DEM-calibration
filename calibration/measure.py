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
    ap.add_argument("final_dump", help="final-state dump file (post-relax heap)")
    ap.add_argument("--settled", help="settled pre-lift dump (for bulk density)")
    ap.add_argument("--plot", help="audit-plot path (default: alongside dump)")
    ap.add_argument("--json", action="store_true", help="print result as JSON")
    args = ap.parse_args()

    result = measure_heap(args.final_dump, settled_dump=args.settled,
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
