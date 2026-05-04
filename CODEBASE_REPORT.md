# Athena++ Codebase Report

> Repository: `/Users/dong/Projects/athena`, version 24.0 (June 2024)
> Scope: 33 subdirectories under `src/`, several hundred .cpp/.hpp files; 9 physics categories under `inputs/`; 23 regression test suites under `tst/regression/`.
> Key references: Stone et al. 2020 ApJS 249:4 (framework), White, Stone & Gammie 2016 (GRMHD).

## 1. What it is

Athena++ is a finite-volume (GR)MHD + AMR framework written in C++11. It runs single-threaded, OpenMP, MPI, or hybrid MPI+OpenMP. The physics it ships covers:

- Newtonian / SR / GR hydrodynamics and MHD
- Self-gravity (FFT and multigrid Poisson solvers)
- Passive scalars
- Chemistry networks (GOW17, KIDA, H2, G14Sod) coupled to optional CVODE
- Radiation transport (explicit and implicit, multi-frequency, multi-group)
- Cosmic-ray transport and multigrid CR diffusion
- Shearing box / orbital advection (FARGO-style)
- Turbulence driving in Fourier space
- Isotropic and anisotropic diffusion (viscosity, conduction, Ohmic / Hall / ambipolar resistivity)

The architectural premise is **bake the configuration into the binary at configure time**. `configure.py` reads the command line and uses `Makefile.in` and `src/defs.hpp.in` as templates to emit a custom `Makefile` and `src/defs.hpp`. Choices like "which problem generator, which coordinate system, which EOS, which Riemann solver, MHD on/off, GR on/off, NGHOST, NSCALARS …" are compiled in. Changing any of these requires `python configure.py … && make clean && make`. Runtime is left only with the athinput file: mesh dimensions, CFL, `tlim`, problem parameters, output specs.

## 2. Build system

### `configure.py` (~1000 lines)

Argument groups:

- **Physics selection**: `--prob`, `--coord`, `--eos`, `--flux`, `--grav`, `--chemistry`, `--chem_ode_solver`, `--chem_radiation`
- **Physics toggles**: `-b` (MHD), `-s` (SR), `-g` (GR), `-t`, `-fft`, `-nr_radiation`, `-implicit_radiation`, `-cr`, `-crdiff`, `-sts`
- **Parallelism / I/O**: `-mpi`, `-omp`, `-hdf5`, `-h5double`
- **Compilers**: `--cxx=...` (g++, g++-simd, icpx, icpc, clang++, aocc, …), `--ccmd`, `--mpiccmd`, `--cflag`, `--include`, `--lib_path`, `--lib`
- **Numerics**: `--nghost`, `--nscalars`, `--nspecies`
- **Library paths**: `--hdf5_path`, `--fftw_path`, `--cvode_path`
- **Debug**: `-debug`, `-coverage`, `-float`

The script also enforces compatibility constraints, e.g. HLLD only with MHD; general EOS only with HLLC/HLLD; `--chemistry` requires `--chem_ode_solver`; `--chem_radiation=six_ray` requires GOW17 or KIDA; GR cannot coexist with radiation transport; `-implicit_radiation` and `-nr_radiation` are mutually exclusive.

### `Makefile.in` and conditional compilation

- `SRC_FILES` uses `wildcard` to pull in `src/bvals/`, `src/hydro/`, `src/field/`, etc. unconditionally.
- Conditional compilation works by **single-file substitution**: `PROBLEM_FILE`, `COORDINATES_FILE`, `EOS_FILE`, `RSOLVER_FILE`/`RSOLVER_DIR`, `CHEMNET_FILE`, `CHEM_ODE_SOLVER_FILE`, `CHEMRADIATION_FILE`, `MPIFFT_FILE`, `GENERAL_EOS_FILE` are template variables that `configure.py` replaces with concrete file paths.
- Object files land in a flat `obj/` directory; `VPATH` maps them back to source subdirectories. Final artifact: `bin/athena`.

### `src/defs.hpp.in`

The macros that `configure.py` emits here drive every compile-time code path:

- **String macros**: `PROBLEM_GENERATOR`, `COORDINATE_SYSTEM`, `RIEMANN_SOLVER`, `EQUATION_OF_STATE`, `CHEMNETWORK_HEADER`
- **Physics gates**: `MAGNETIC_FIELDS_ENABLED`, `SELF_GRAVITY_ENABLED` (0/1/2 → none/FFT/MG), `NR_RADIATION_ENABLED`, `IM_RADIATION_ENABLED`, `CR_ENABLED`, `CRDIFFUSION_ENABLED`, `CHEMISTRY_ENABLED`, `CHEMRADIATION_ENABLED`, `STS_ENABLED`, `RELATIVISTIC_DYNAMICS`, `GENERAL_RELATIVITY`
- **Array dimensions**: `NHYDRO`, `NFIELD`, `NWAVE`, `NSCALARS`, `NSPECIES`, `NGHOST`, `NGRAV`, `NCR`, `NRAD`
- **Backends**: `MPI_PARALLEL`, `OPENMP_PARALLEL`, `HDF5OUTPUT`, `FFT`, `CVODE`, `SINGLE_PRECISION_ENABLED`

## 3. Core framework

### 3.1 Top-level driver

`src/main.cpp` (~600 lines) follows a strict sequence:

1. MPI/OpenMP init (`MPI_Init_thread`, `MPI_THREAD_MULTIPLE` for hybrid)
2. CLI parse (`-i` input, `-r` restart, `-d` rundir, `-m` mesh-decomposition dry run, `-t` walltime, `-n` parse-only)
3. `ParameterInput` loads athinput
4. `Mesh` constructor (fresh or from restart)
5. Build task lists (`TimeIntegratorTaskList` plus STS, chem_rad, etc. as enabled)
6. `Mesh::Initialize()` calls problem generator or loads restart data
7. `Outputs` set up + initial dump
8. **Main loop**: execute task list across RK substages → optional STS / turbulence drive / CR diffusion / implicit radiation iteration / self-gravity → `LoadBalancingAndAdaptiveMeshRefinement` → `NewTimeStep` → intermediate dumps → check SIGTERM/SIGINT/SIGALRM/walltime
9–10. Final dump, zone-cycles/cpu-second diagnostics, cleanup, `MPI_Finalize`

### 3.2 Mesh / MeshBlock / MeshBlockTree (`src/mesh/`)

- **`MeshBlockTree`** (`meshblock_tree.cpp`): global octree, each node carries a `LogicalLocation{lx1, lx2, lx3, level}`. The `lx*` fields are 64-bit so the tree can hold >30 levels of AMR. Operations: `Refine`, `Derefine`, `FindMeshBlock`, `FindNeighbor`.
- **`Mesh`** (`mesh.cpp`): the global object. Owns `nbtotal`, `nblocal`, `my_blocks` (this rank's blocks), `loclist` (global LogicalLocation table), `ranklist[i]` / `nslist[rank]` / `nblist[rank]` for the rank distribution, the tree root, and the AMR `nref/nderef` flag arrays.
- **`MeshBlock`** (`meshblock.cpp`): a single grid patch plus pointers to its physics objects: `pcoord`, `peos`, `phydro`, `pfield`, `pscalars`, `pgrav`, `pnrrad`, `pcr`, `pchemnet`, `pmr`, `pbval`. Whether each is allocated is decided by `defs.hpp`. Cell index range: `is/ie/js/je/ks/ke` is the active region; ghost zones extend by `NGHOST` on each side.

### 3.3 AMR and load balancing (`src/mesh/mesh_refinement.cpp`, `amr_loadbalance.cpp`)

- The user enrolls a refinement condition via `EnrollUserRefinementCondition()`. Each step the callback writes `refine_flag_ ∈ {-1, 0, +1}` for each block.
- **Restriction**: cell-centered quantities are volume-weighted-averaged; face-centered fields use **sums** rather than averages (preserves flux).
- **Prolongation**: cell-centered uses piecewise-linear interpolation; face fields are split into shared-face (`ProlongateSharedField*`) and interior (`ProlongateInternalField`) operators that together preserve div(B) = 0.
- **Load balancing** (`Mesh::LoadBalancingAndAdaptiveMeshRefinement`):
  1. `MPI_Allgather` collects all refine/derefine flags, rebuilds the tree, reassigns global block IDs.
  2. `UpdateCostList` accumulates an exponentially weighted runtime estimate per block.
  3. `CalculateLoadBalance` greedily packs the most expensive blocks onto ranks, targeting `totalcost/Nranks` per rank.
  4. `RedistributeAndRefineMeshBlocks` migrates block data asynchronously along the space-filling curve.

### 3.4 Task DAG (`src/task_list/`)

Each task is a `(TaskID, dependency, TaskFunc)` tuple. `TaskID` is a 128-bit bitset. `TaskStatus` returns `TASK_FAIL/SUCCESS/NEXT` — `NEXT` means continue with the same block; `SUCCESS` rotates to the next block (better cache and load behavior).

The main integrator `TimeIntegratorTaskList` (`time_integrator.cpp`) supports vl2, rk2, rk3, rk4, ssprk5_4 with low-storage Ketcheson (2010) coefficients. Tasks include ClearAllBoundary, CalculateHydroFlux, CalculateEMF, SendHydroFlux, ReceiveAndCorrectHydroFlux, IntegrateHydro, SetBoundaries, ProlongateBoundaries, PhysicalBoundary, UserWorkInLoop, and so on.

Auxiliary physics each has its own task list:

- `sts_task_list.cpp` — super-time-stepping (see §5.10)
- `mg_task_list.cpp`, `grav_task_list.cpp` — multigrid V-cycles and gravity boundaries
- `im_rad_task_list.cpp` / `im_radit_task_list.cpp` / `im_radhydro_task_list.cpp` / `im_rad_compt_task_list.cpp` — implicit radiation, radiation–hydro coupling, Compton scattering
- `chem_rad_task_list.cpp` — six-ray column densities + photo-rate updates
- `crdiffusion_task_list.cpp` — CR diffusion boundaries

### 3.5 Boundary values (`src/bvals/`)

- Pattern: `BoundaryBase` → `BoundaryValues` (one aggregator per MeshBlock) → `BoundaryVariable` (one per physical quantity, e.g. `CellCenteredBoundaryVariable`, `FaceCenteredBoundaryVariable`, `RadiationBoundaryVariable`, `OrbitAdvectionBoundaryVariable`, `SixrayBoundaryVariable`).
- Subdirectory split: `cc/` for cell-centered, `fc/` for face-centered (B), `orbital/` for shearing-box / orbital advection, `sixray/` for chemistry radiation.
- A 3D AMR block can have up to 56 neighbors (6 face + 12 edge + 8 corner, plus refined variants).
- Buffers: each `BoundaryVariable` owns `BoundaryData` + per-neighbor `send_buf_/recv_buf_`. Inter-rank traffic uses async `MPI_Isend/Irecv`; intra-rank neighbors copy via `CopyVariableBufferSameProcess`.
- AMR boundaries (`bvals_refine.cpp`): cross-level data is prolongated (coarse→fine) via `ProlongateBoundaries`, and fine-block fluxes are sent back for correction on the coarse side to preserve flux conservation.

### 3.6 Foundational primitives

- **`AthenaArray<T>`** (`src/athena_arrays.hpp`): templated 1D–6D array, one contiguous allocation, indexed `A(n,k,j,i) = A[i + nx1*(j + nx2*(k + nx3*n))]` (i varies fastest). `InitWithShallowSlice()` produces non-owning views. A `DataStatus` enum tags arrays as empty / shallow_slice / allocated. This array is the central performance abstraction — shallow slicing lets inner kernels avoid any copy.
- **`ParameterInput`**: athinput parser. `InputBlock` singly-linked list of `<block>` sections, each holding an `InputLine` list of `key=value`. API: `GetReal/GetInteger/GetString/GetOrAdd*`. OpenMP-safe via `omp_lock`. Command-line `-i key=value` overrides take effect after the file is read.
- **`Globals`** (`src/globals.hpp`): just `my_rank` and `nranks`.

### 3.7 Utilities (`src/utils/`)

Signal handling (`signal_handler.cpp` — SIGTERM triggers a graceful checkpoint), MPI buffer pack/unpack, table interpolation (used by tabulated EOS), Gauss–Legendre quadrature (radiation angular discretization), dense matrix multiply, Numerical Recipes RNG (`ran2`), vector rotation, `change_rundir`, `show_config` (the `-c` CLI flag dumps compile-time settings).

## 4. Core physics modules

### 4.1 Hydro (`src/hydro/`)

The `Hydro` class owns `u`, `u1` (two integrator registers), `w`, `w1`, `flux[3]`, plus STS registers `u2/u0/fl_div`, helpers `dvn/dvt`, and `hbvar`, `hsrc`, `hdif`.

Three-step update pipeline:

1. `calculate_fluxes.cpp` — reconstruct → Riemann → flux. In MHD it also maintains corner EMFs and CT weight arrays.
2. `add_flux_divergence.cpp` — `u_out -= w·(A·F)/V` accumulated across the three directions with proper geometric scaling.
3. `new_blockdt.cpp` — CFL using `SoundSpeed` / `FastMagnetosonicSpeed`.

`MAGNETIC_FIELDS_ENABLED` changes the Riemann solver signature: hydro version is `(k,j,il,iu,ivx, wl,wr, flx, dxw)`; MHD version adds `bx, ey, ez, wct` (transverse field, corner EMF, CT weight).

### 4.2 Riemann solvers (`src/hydro/rsolvers/{hydro,mhd}/`)

**Hydro**: HLLE (most diffusive), HLLC (three-wave, recommended general purpose), Roe (linearized exact, least diffusive but needs EOS floors), LLF, LHLLC (low-dissipation HLLC). Each has `_rel` (SR/GR with frame transform) and `_rel_no_transform` variants.

**MHD**: HLLD (Miyoshi–Kusano five-wave, the recommended default), HLLD_ISO (isothermal), HLLE_MHD, LLF_MHD, Roe_MHD, LHLLD.

### 4.3 Reconstruction (`src/reconstruct/`)

DC, PLM (minmod and van Leer limiters), PPM (`ppm.cpp` with Colella–Sekora extremum-preserving limiter; `ppm_simple.cpp` McCorquodale–Colella with Mignone curvilinear corrections; `ppm_fast.cpp` skips characteristic projection for speed), WENO5 (`weno.cpp`, both WENOZ and WENOMZ).

Each method has three overloads: full (hydro + MHD primitives), simple (scalar-only), and reordered (`[k,j,i,n]` vs `[n,k,j,i]` memory layout). The `characteristic_projection_` flag toggles whether limiting is done in characteristic space — required for MHD stability.

### 4.4 Field and constrained transport (`src/field/`)

- Layout: face fields `b.x1f/x2f/x3f`, derived cell-centered `bcc`, integrator registers `b/b1/b2`, STS registers `b0/ct_update`, edge EMFs `e.x1e/x2e/x3e`, CT weights `wght.x{1,2,3}f`.
- `ct.cpp` implements `dB/dt = -∇×E`: e.g. `b1f -= (wght/A)·[E3(j+1) - E3(j)]`. This is the mechanism that holds div(B) at machine precision.
- `calculate_corner_e.cpp` builds `E = -v×B` from face velocities and cell-centered B at cell corners; in GR it transforms to 4-velocities and 4-magnetic fields, with special-cased pole handling for spherical coords.
- `CalculateCellCenteredField` is a 6-face average producing `bcc`.
- Non-ideal MHD (`field_diffusion/`): `eta_ohm`, `eta_hall`, `eta_ad`, each contributing an edge EMF that is added in `ct.cpp`. `jcc` is the cell-centered current density.

### 4.5 EOS (`src/eos/`)

A 2 × 2 × 3 matrix: adiabatic vs isothermal × hydro vs MHD × Newtonian/SR/GR. Core virtuals: `ConservedToPrimitive` (iterates for the Lorentz factor in SR/GR), `PrimitiveToConserved`, `ConservedToPrimitiveCellAverage` (4th-order path), `ApplyPrimitiveFloors`, plus the speed family (`SoundSpeed`, `FastMagnetosonicSpeed`, `SoundSpeedsSR/GR`, `FastMagnetosonicSpeedsGR`).

`general/` holds extensible variants: `eos_table.cpp` (tabulated, e.g. from stellar evolution output), `hydrogen.cpp` (ionization equilibrium), `ideal.cpp`, `noop.cpp`.

### 4.6 Coordinates (`src/coordinates/`)

Newtonian: `cartesian`, `cylindrical`, `spherical_polar`. GR: `minkowski`, `schwarzschild`, `kerr-schild`, `gr_user` (custom-metric template).

Virtual interface: `CellVolume`, `Face{1,2,3}Area`, `Edge{1,2,3}Length`, `CenterWidth*`, `AddCoordTermsDivergence` (curvilinear centrifugal/Coriolis terms, GR geometric source terms), `{Cell,Face*}Metric`, Laplacians. GR coordinates pre-compute and cache metric, inverse, and derivative scalars to avoid recomputing sin/cos/sqrt every step.

### 4.7 Passive scalars (`src/scalars/`)

`PassiveScalars` owns conserved `s[NSCALARS]` (mass density per species), primitive `r[NSCALARS]` (mass fraction = s/ρ), `s_flux[3]`, and 4th-order helpers `mass_flux_fc[3]`, `s_cc/r_cc`. Advection rides on the hydro mass flux. Optional isotropic diffusion via `scalar_diffusion.cpp` (`nu_scalar_iso`). `NSPECIES` (chemistry) shares this storage backbone.

### 4.8 Orbital advection / shearing box (`src/orbital_advection/` + `src/bvals/orbital/`)

FARGO-style: separate fast orbital motion from slower dynamical evolution. Each step caches orbital velocity at cell centers/faces, uses 1D PLM/PPM remap (2D under AMR) on conserved variables and EMFs, then `ConvertOrbitalSystem` converts back to the inertial frame. Orbital velocity is coordinate-aware: `CartOrbitalVelocity` (shearing box, Ω₀, q), `CylOrbitalVelocity2D/3D` (Keplerian), `SphOrbitalVelocity`. Shearing-box BCs use `OrbitalBoundaryCommunication` to remap ghost cells across shear-periodic faces.

### 4.9 Physical diffusion

- **Hydro** (`src/hydro/hydro_diffusion/`): isotropic and anisotropic viscosity and thermal conduction. `NewDiffusionDt` applies the parabolic CFL `Δt ~ ν·Δx⁻²` (which dominates the timestep when STS is off).
- **Field** (`src/field/field_diffusion/`): Ohmic, Hall (currently commented out in source), ambipolar.

### 4.10 Units (`src/units/`)

The `Units` class takes three primitives — `code_mass_cgs`, `code_length_cgs`, `code_time_cgs` — and derives density/velocity/pressure/magnetic-field conversions to CGS. It also pre-computes G, M☉, L☉, Myr, pc, kB, c, and friends in code units.

## 5. Auxiliary physics

### 5.1 Self-gravity (`src/gravity/`)

- **FFT solver** (`fft_gravity.{hpp,cpp}`, derived from `FFTBlock`): forward FFT → apply Poisson kernel in k-space → inverse FFT. `FFTGravityDriver` orchestrates across blocks. **Requires uniform mesh** (validated at `fft_driver.cpp` startup).
- **Multigrid solver** (`mg_gravity.{hpp,cpp}`): red-black Gauss–Seidel smoother + restriction + prolongation + FAS residuals, V-cycle. `MGGravityDriver` manages the grid hierarchy. 3D only.
- Coupling: `SelfGravity()` in `src/hydro/srcterms/hydro_srcterms.cpp` adds `ρ∇φ·dt` to the momentum equations.
- 4πG is set by the problem generator via `Mesh::SetFourPiG()`.

### 5.2 Multigrid framework (`src/multigrid/`)

`Multigrid` base class manages a tower of `MGOctet{u, src, def, operator coefficients}` grids. `MGBoundaryValues` handles periodic / zero-gradient / zero-fixed / multipole BCs. `MultigridTaskList` (`mg_task_list.cpp`) schedules the V-cycle as a "restriction / red-black smoothing / prolongation / residual" DAG. Both gravity and CR diffusion plug into this.

### 5.3 FFT (`src/fft/`)

Built on FFTW3 + the Plimpton parallel FFT library (`src/fft/plimpton/`'s `fft_2d.h`, `fft_3d.h`). `FFTDriver` manages the rank-block mapping, MPI sub-communicators, and plan caches. 3D FFTs use pencil decomposition with axis-by-axis all-to-all transposition, scaling to thousands of ranks.

### 5.4 Turbulence driving (`src/fft/turbulence.cpp`)

`TurbulenceDriver` injects driven turbulence in Fourier space using an Ornstein–Uhlenbeck process. `Generate/OUProcess/Perturb/Project` control the spectrum, energy injection rate, and projection onto compressive vs solenoidal modes. The driving enters hydro as a momentum source term.

### 5.5 Non-relativistic radiation (`src/nr_radiation/`)

`NRRadiation` carries `ir[nang, nfreq, k, j, i]` for angle- and frequency-resolved specific intensity, plus a 13-component `rad_mom` (energy density, three-flux, pressure tensor, etc.). Angular grid is Cartesian (θ,φ) or polar (μ,φ); frequency grid linear or logarithmic.

- **Explicit** (`integrators/rad_integrators.cpp`): `CalculateFluxes` (angular first-order upwind) → `AddSourceTerms` (absorption, scattering, Compton) → `LabToCom/ComToLab` (Doppler, aberration).
- **Implicit** (`implicit/radiation_implicit.cpp`): standard Jacobi or scheduled relaxation Jacobi (SRJ). Three task lists: `IMRadITTaskList` (radiation-only iteration), `IMRadHydroTaskList` (radiation–hydro coupling), `IMRadComptTaskList` (Compton scattering).

### 5.6 Cosmic-ray transport (`src/cr/`)

`CosmicRay` owns `u_cr[4]` (energy + 3-flux). The transport equation is

```
∂E_cr/∂t + ∇·(E_cr v_adv) − ∇·(σ_diff ∇E_cr) = S
```

with anisotropic diffusion aligned to **B**. `CRIntegrator` is explicit; coupling to hydro is via CR pressure gradient and streaming velocity.

### 5.7 CR diffusion via multigrid (`src/crdiffusion/`)

When CR diffusion timescales are stiff, switch to implicit multigrid: `CRDiffusion` wraps `MGCRDiffusion` (a `Multigrid` subclass) whose stencil coefficients come from local B strength and orientation. `CRDiffusionBoundaryTaskList` handles ghost-zone exchange independently of the main hydro loop.

### 5.8 Chemistry (`src/chemistry/`)

`NetworkWrapper` virtual interface: `InitializeNextStep / RHS / Edot / Jacobian`. Concrete networks:

- **GOW17** — 17 species, includes H₂ and CO chemistry, UV heating/cooling
- **KIDA** — hundreds of ion–molecule reactions with optional self-shielding
- **H2** — minimal H/H₂ network for disk simulations
- **G14Sod** — 4-species network for shock tests

ODE solvers: `ODEWrapper` wraps SUNDIALS CVODE (BDF + sparse Jacobian, needed for stiff KIDA networks) or a forward-Euler integrator (no CVODE dependency). Species reuse the `PassiveScalars` storage; `NSPECIES` sets the array dimension.

### 5.9 Chemistry–radiation coupling (`src/chem_rad/`)

`ChemRadiation` carries specific intensity `ir` and averaged `ir_avg`. Two integrators:

- **six-ray** (`integrators/six_ray.cpp`): traces along ±x/±y/±z, computes column densities, applies dust + H₂ self-shielding from `chemistry/utils/shielding.cpp`, feeds photoionization/photodissociation rates back into the chemistry network.
- **const_rad** (`integrators/const_rad.cpp`): isotropic background — testing or distant sources.

`ChemRadiationIntegratorTaskList` builds the six-ray work as a DAG: `GetColMB_ix1/ox1/…` → `RecvAndSend_*` (MPI stitches columns across the domain) → `UpdateRadiationSixRay`.

### 5.10 Super-time-stepping (`src/task_list/sts_task_list.cpp`)

For parabolic operators (viscosity, conduction, resistivity, scalar diffusion), Athena++ uses Meyer et al. (2014) RKL1/RKL2: a multi-stage Runge-Kutta-Legendre scheme that absorbs the diffusion timescale into a **single** hydro Δt by taking many (often dozens of) substeps. This dodges the `Δt ~ Δx²/ν` parabolic CFL. `sts_max_dt_ratio` controls the number of stages per STS step.

## 6. I/O and visualization

### 6.1 Outputs (`src/outputs/`)

`OutputType` is an abstract base with concrete implementations:

- `HistoryOutput` (`history.cpp`) — `.hst` time-series
- `VTKOutput` (`vtk.cpp`) — legacy VTK
- `FormattedTableOutput` (`formatted_table.cpp`) — ASCII `.tab`, supports slicing and summation
- `RestartOutput` (`restart.cpp`) — binary `.rst`, serial header followed by collective writes of conserved variables, face fields, scalars, radiation, CR per block
- `ATHDF5Output` (`athena_hdf5.cpp`) — HDF5 `.athdf` + XDMF; templated `h5out_t` supports float/double/uint8 with vmin/vmax normalization for integer casts

`io_wrapper.cpp` abstracts MPI-IO vs serial I/O. `OutputData` is a doubly-linked list of array views; problem generators register custom output variables through the `MeshBlock::UserWorkBeforeOutput` hook.

### 6.2 athinput format

Sections: `<comment>`, `<job>`, `<output*>`, `<time>` (`cfl_number`, `tlim`, `nlim`, `integrator`, `xorder`), `<mesh>` (`nx*`, `x*min/max`, `ix*_bc`/`ox*_bc`), `<meshblock>`, `<coordinates>`, `<hydro>`, `<mhd>`, `<problem>`, `<gravity>`, `<radiation>`, `<chemistry>`, etc. The `inputs/` directory is organized by physics regime: hydro, mhd, hydro_gr, mhd_gr, hydro_sr, mhd_sr, radiation, chemistry, cosmic_ray.

### 6.3 Visualization (`vis/`)

- **`vis/python/athena_read.py`** — `hst()`, `tab()`, `vtk()`, `athdf5()`, `error_dat()`, `check_nan()`, returning NumPy dicts/arrays. `hst()` detects restart branches by checking time monotonicity and (in non-raw mode) deduplicates automatically.
- `vis/visit/` — VisIt Python scripts and plugins for interactive 3D rendering.
- `vis/vtk/` — ParaView `.vti`/`.vtu` reader scripts.

## 7. Problem generators (`src/pgen/`)

`default_pgen.cpp` provides weak-symbol (GCC `__attribute__((weak))`) defaults for every hook so users only override what they need:

- **Mesh-level**: `InitUserMeshData`, `UserWorkInLoop`, `UserWorkAfterLoop`
- **MeshBlock-level**: `InitUserMeshBlockData`, `ProblemGenerator` (the main IC entry point), `UserWorkInLoop`, `UserWorkBeforeOutput`
- **Enrollment hooks**: `EnrollUserBoundaryFunction`, `EnrollUserRefinementCondition`, `EnrollUserExplicitSourceFunction`, `EnrollUserGravityFunction`, etc.

Catalog by regime (representative, not exhaustive): shock_tube, blast, dmr, orszag_tang, cpaw, kh, disk, binary_gravity, collapse, turb, gr_blast, gr_bondi, gr_torus, gr_mhd_inflow, cr_diffusion, chem_* (eight variants), from_array (initialize from external data). This directory is the main entry point for new science / new papers.

## 8. Tests and CI

### 8.1 Regression tests (`tst/regression/`)

`run_tests.py` discovers and runs `scripts/tests/<suite>/<name>.py` modules. Each test exports `prepare()` (`athena.configure` + `athena.make`), `run()` (`athena.run` / `athena.mpirun`), and `analyze()` (parses `.hst`/`.tab`/`.vtk`/`.athdf` and compares to references). Each test **re-configures and rebuilds** Athena++, so a full run is slow — pick a suite or single test during development.

The 23 suites: amr, chemistry, cr, curvilinear, diffusion, eos, fft, gr, grav, hybrid, hydro, hydro4 (4th-order), implicit_radiation, mhd, mpi, multi_group, nr_radiation, omp, outputs, pgen, scalars, shearingbox, sr, symmetry, turb.

`scripts/utils/athena.py` is the Python wrapper: `configure / make / run / mpirun / restart / save_files / restore_files`. The last two save and restore the developer's `defs.hpp` and `Makefile` so tests don't trample your in-progress build.

### 8.2 Style (`tst/style/`)

- `cpplint.py` + `CPPLINT.cfg` (line length 90, header guard root `./src/`, several whitespace categories disabled).
- Custom `check_athena_cpp_style.sh`:
  - **Bug-class**: tabs forbidden.
  - **Portability**: `std::sqrt/log/exp/pow/abs` only — no bare `sqrt`, `fabs`, etc.
  - **Style**: no `}}` on a single line, `#pragma` left-justified, no trailing whitespace, src/ files must be mode 644 (checked via `git ls-tree`).
- `setup.cfg` configures flake8 for Python files (also max-line-length 90).

### 8.3 CI (`tst/ci/`)

- `jenkins/` — Groovy pipelines for the Princeton Jenkins server (auto-runs on master).
- `container/` — Dockerfile for containerized CI builds.
- `set_warning_cflag.sh` — adds `-Wall -Wextra` for CI.
- `.codecov.yml` — minimum 50% coverage in `src/`, max 2% drop on PRs, Slack webhook on failure.

## 9. Compile-time gates — quick reference

| Macro | Effect |
|---|---|
| `MAGNETIC_FIELDS_ENABLED` | Whether `Field` exists; Riemann solver signature; CT; corner EMF; field diffusion |
| `RELATIVISTIC_DYNAMICS` | EOS picks `SoundSpeedsSR/GR`; Riemann solvers use `_rel` variants |
| `GENERAL_RELATIVITY` | Coordinate metric caches; GR sound speeds; geometric source terms in `AddCoordTermsDivergence` |
| `SELF_GRAVITY_ENABLED` (1/2) | FFT vs multigrid; gates `hydro_srcterms.cpp::SelfGravity` |
| `NR_RADIATION_ENABLED` / `IM_RADIATION_ENABLED` | Explicit vs implicit radiation task lists; mutually exclusive |
| `CR_ENABLED` / `CRDIFFUSION_ENABLED` | Explicit CR transport / multigrid CR diffusion |
| `CHEMISTRY_ENABLED` / `CHEMRADIATION_ENABLED` | Network + CVODE + six-ray raytrace |
| `STS_ENABLED` | `SuperTimeStepTaskList` |
| `NSCALARS` / `NSPECIES` | Scalar/chemistry array dimensions and loop bounds |
| `NGHOST` | Ghost zone width (driven by reconstruction order) |
| `SINGLE_PRECISION_ENABLED` | `Real` is float vs double; `MPI_ATHENA_REAL` |

## 10. Observations

**Strengths**

1. **Configure-time baking** keeps the binary lean: with MHD off, `Field` doesn't exist and `if (MAGNETIC_FIELDS_ENABLED)` is dead-code-eliminated. Both performance and code clarity benefit.
2. **MeshBlock as the physics container** decouples modules cleanly. Adding a new per-block physics module (radiation, CR, …) is mechanical: a class + conditional construction in `MeshBlock` ctor + a registered `BoundaryVariable` + a task list.
3. **Task DAG** interleaves async communication, computation, and AMR sync, but adding new tasks is a routine pattern.
4. **Regression suite re-configures every test**, which is unusual for a research code but really does cover the compile-time combinatorics.

**Cognitive load**

1. There are many physics modules (chemistry, radiation, CR, gravity, turbulence, shearing box, …), each with its own task list and BoundaryVariable. Tracing one full timestep can mean hopping across a dozen files. A "big-picture" CLAUDE.md note is genuinely helpful here.
2. `configure.py`'s compatibility matrix has non-obvious edges (no GR + radiation, general EOS only with HLLC/HLLD, etc.) that aren't always documented outside the script's error messages.
3. CT with weights and corner EMFs is more implicit than the published Stone+2008 description; fitting non-ideal MHD EMFs into CT (e.g. how `OhmicEMF`/`AmbipolarEMF` flow into `ct.cpp`) requires reading the source rather than the wiki.
4. The 4th-order ("hydro4") path requires `ConservedToPrimitiveCellAverage` from EOS and `mass_flux_fc` deep copies for passive scalars — easy to miss when adding a new physics module.

**Suggested reading order for newcomers**

1. `src/main.cpp` — get the big-picture loop.
2. `src/mesh/{mesh,meshblock,meshblock_tree}.cpp` and `src/task_list/{task_list,time_integrator}.cpp`.
3. End-to-end through one specific physics: `src/pgen/blast.cpp` → `src/hydro/{hydro,calculate_fluxes,add_flux_divergence,new_blockdt}.cpp` → `src/reconstruct/plm.cpp` → `src/hydro/rsolvers/hydro/hllc.cpp`.
4. Add MHD: `src/field/{ct,calculate_corner_e}.cpp`.
5. AMR: `src/mesh/{mesh_refinement,amr_loadbalance}.cpp` and `src/bvals/bvals_refine.cpp`.
6. Optional physics (radiation, CR, chemistry) — they're well-isolated, read only the ones you need.
