# Drawdown Flow-Rate Target — Literature Search Result (Phase 9 close-out)

> ⚠️ **Outcome: the literature CANNOT supply a discriminating target for our
> orifice.** A deep multi-source search (2026-06-12, 18 sources fetched, 25
> claims source-verified, 1 killed in adversarial review) found **no Beverloo
> constants fitted specifically for wheat** and no wheat discharge data at
> orifice scales near ours. The best literature-grounded value is a **soft
> model-based target ≈ 40 ± 12 g/s** — and since the simulated friction
> valley spans only 40.0–46.3 g/s, a σ of 12 g/s cannot separate family
> members. The drawdown response keeps its (verified) discriminating power
> for the day a real target exists; until then the Phase-9 equivalence-family
> closure stands.

**Geometry this target applies to:** flat-bottom cylinder Ø80 mm, concentric
circular floor orifice **D₀ = 22 mm**, wheat PSD d ≈ 3.7 mm, ρ_b ≈ 780 kg/m³
(templates/drawdown.in).

## What the search established

| Finding | Confidence | Key sources |
|---|---|---|
| Beverloo form ṁ = C·ρ_b·√g·(D₀ − k·d)^2.5 is canonical for flat-bottom circular-orifice discharge | high | Beverloo et al. 1961 (Chem. Eng. Sci. 15:260); Mankoc et al. 2007 (arXiv:0707.4550) |
| Generic constants: C ≈ 0.58 (0.55–0.65); k ≈ 1.4–1.5 for spheres, shape-dependent, plausibly up to ~2.5 for elongated grains | high | Thermopedia; Mamtani thesis (UF); Calderón et al. 2017 |
| **No study reports C, k fitted for wheat.** Calderón 2017 fits seeds (lentils, rice) but excludes wheat; Chang/Converse/Steele 1988 (vertical orifices, USDA) fits a plain power law Q = k·Dⁿ for wheat, not Beverloo; Wiacek 2023 gives wheat flow only as normalized figure data in conical orifices | high | Powder Technol. S0032591017305417; USDA ARS PDF; Sci. Rep. 13 (PMC9837167) |
| All wheat measurements are at 10.2–30.5 **cm** orifices (5–12× ours) or non-flat geometry — any wheat-grounded fit is a large extrapolation | high | Chang & Converse 1988 (Trans. ASAE 31(1):300, paywalled); seeder study S1881836616300143 |
| Prediction for D₀ = 22 mm spans **25–58 g/s** across plausible constants; central (C 0.58, k 1.9) ≈ 39 g/s → **soft target 40 ± 12 g/s**. k dominates the spread (~2× swing); C contributes ~±10% | medium | computed from the above |
| **Regime caution:** D₀/d ≈ 5.9 sits just above the jamming/intermittency threshold Rc ≈ 5 — the lower edge of Beverloo validity (our simulated discharge showed no intermittency: mass-vs-time r² > 0.998) | high | Mankoc et al. 2007 |
| **Bulk-density disagreement flagged:** Wiacek 2023 measured wheat ρ_b = 711.7 ± 5.7 kg/m³, ~9% below our 780; flow is linear in ρ_b → central prediction ~35 g/s at their value | high | Sci. Rep. 13, Table 1 (verified via PMC) |

## Why this cannot break the valley

The Phase-9 probe measured the equivalence family spanning **46.3 → 40.0 g/s**
(fric 0.25 → 0.60, 8.2× seed noise — the *instrument* discriminates). Against
a 40 ± 12 g/s target the σ-normalized loss varies by only ~0.5σ across the
whole family: a mild preference for the high-fric end, not a calibration.
Using it as a hard third objective would manufacture false precision; it is
recorded here as a **consistency check (passed — the family sits inside the
band) and a weak directional hint**, nothing more.

## Routes to a real target (recorded for later)

1. **Physical measurement** — the drawdown rig is by far the cheapest of the
   three tests to build (bin + orifice plate + scale + stopwatch). A measured
   target at ±2 g/s would collapse the family decisively (signal/σ ≈ 3.4).
2. **Chang & Converse 1988 full text** (Trans. ASAE 31(1):300–304, horizontal
   floor orifices — paywalled): its tabulated wheat rates could anchor a fit,
   but its orifices are 10.2–25.4 cm, so it would also require simulating a
   much larger geometry (≳30 cm bin, ~10× particles/runtime) to compare
   without extrapolating.
3. **Wiacek 2023 raw data** ("available on request") could yield absolute
   wheat rates, but for conical (45°) orifices — a different template.
4. A wheat-specific k via Calderón's surface-area correlation applied to
   wheat shape parameters — would shrink σ somewhat, not to discriminating
   levels.

## Sources (verified set)

- Beverloo, Leniger, Van de Velde (1961). *The flow of granular solids
  through orifices.* Chem. Eng. Sci. 15:260–269.
- Mankoc et al. (2007). *The flow rate of granular materials through an
  orifice.* arXiv:0707.4550.
- Calderón et al. (2017). *Correlation between discharge rates and particle
  properties for food seeds.* Powder Technology (S0032591017305417) — fits
  Beverloo for lentils/rice, **not wheat**; full text 403-blocked.
- Chang, Converse, Steele (1988). *Flow rates of grain through vertical
  orifices.* USDA ARS (open PDF) — wheat power-law fit, 10.2–30.5 cm.
- Chang & Converse (1988). *Flow rates of wheat and sorghum through
  horizontal orifices.* Trans. ASAE 31(1):300–304 — **paywalled, unverified**.
- Wiacek et al. (2023). *Experimental and DEM study of the silo discharge.*
  Sci. Rep. 13 (PMC9837167) — wheat properties Table 1 verified; flow data
  normalized/figure-only, conical orifices.
- Thermopedia, *Granular flow through orifices*; Mamtani MSc thesis (U.
  Florida) — generic Beverloo constants.

Full machine-verified claim set: deep-research run 2026-06-12 (5 search
angles, 100 agents; stats: 56 claims extracted, 25 verified, 24 confirmed,
1 refuted).
