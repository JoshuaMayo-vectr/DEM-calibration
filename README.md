# DEM-calibration

A calibration pipeline for Discrete Element Method (DEM) contact-model parameters over [LIGGGHTS-PUBLIC 3.8.0](https://github.com/CFDEMproject/LIGGGHTS-PUBLIC): measure cheap bulk responses of a real granular material (angle of repose, bulk density, flow rate), simulate the same tests, and search the parameter space until simulation matches reality. Calibrated material parameter sets come out as versioned, evidenced artifacts.

The full plan, locked design decisions, and phase-by-phase status live in **[ROADMAP.md](ROADMAP.md)**.

## Repository layout

```
DEM-calibration/
├── ROADMAP.md            ← big-picture roadmap (start here)
├── external/             ← LIGGGHTS-PUBLIC source + built binary (gitignored; recipe below)
├── templates/            ← parameterized LIGGGHTS input scripts (aor.in, drawdown.in)
├── calibration/          ← Python driver: runner.py, measure.py, optimize.py
├── experiments/          ← measured physical data + protocol
├── materials/            ← calibrated material cards (the deliverable)
├── results/              ← trial directories, LHS screen, optimizer studies
└── docs/                 ← knob catalog, notes
```

## Setup

Target platform: macOS arm64 (Apple Silicon). Prerequisites: Xcode command-line tools, [Homebrew](https://brew.sh).

### 1. LIGGGHTS build (engine)

`external/` is gitignored — rebuild it from source:

```sh
brew install open-mpi boost

mkdir -p external && cd external
git clone https://github.com/CFDEMproject/LIGGGHTS-PUBLIC.git
cd LIGGGHTS-PUBLIC
git checkout 3d5c00f   # commit this pipeline was built against

cd src
make auto              # first run generates src/MAKE/Makefile.auto and the auto config
```

**Required build settings** (in the generated auto-build config):

- `USE_VTK = "OFF"` — Homebrew ships VTK 9.x; LIGGGHTS 3.8 supports only VTK ≤ 8. Nothing downstream needs the VTK build: output is plain-text `dump custom`, which OVITO reads natively.
- `BOOST_INC_USR = /opt/homebrew/include` — point Boost at the Homebrew prefix.

Apple clang compiles the 2018 codebase with warnings only. The result is `src/lmp_auto`.

**Known tutorial fix:** some bundled tutorial scripts use `dump custom/vtk`, which fails on a no-VTK build — swap to `dump custom`.

**Smoke test:**

```sh
cd ../examples/LIGGGHTS/Tutorials_public/packing
mpirun -np 2 ../../../../src/lmp_auto -in in.packing   # writes dumps to post/
```

### 2. Python environment (driver layer)

Python 3.11+ required (the `ovito` pip package ships arm64 wheels for recent CPython only; built against 3.13):

```sh
python3.13 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -c "import optuna, jinja2, ovito"   # should print nothing
```

### 3. OVITO desktop (interactive visualization)

```sh
brew install --cask ovito
```

Drag any `post/*.liggghts` dump file into OVITO to play the time series.
