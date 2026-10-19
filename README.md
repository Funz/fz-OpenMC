# fz-OpenMC

[fz](https://github.com/Funz/fz) plugin for [OpenMC](https://docs.openmc.org) (Monte Carlo
particle transport code): parametric criticality (eigenvalue) and fixed-source studies, with
either input form of OpenMC — a Python script using the `openmc` API, or XML files.

## Features

- Variables and formulas in OpenMC Python scripts and XML files
- Extraction of the run status (with the first error message), the combined keff and its
  standard deviation, the leakage fraction, and every tally of `tallies.out`
- Success decided from the OpenMC output (`RESULTS` banner, statepoint file), not only from
  the exit code
- Output extraction in Python (fz `python://` expressions): no bash, awk or grep needed to
  parse results, LF and CRLF line ends accepted

### Input

The calculator script runs OpenMC in the case directory on:

- a **Python script** (`*.py` importing `openmc`, e.g. `sphere.py`): the script is run, then
  - if it only exports the model (`model.export_to_model_xml()` or `model.export_to_xml()`),
    OpenMC is run on the exported XML (threads and MPI settings below apply);
  - if it runs OpenMC itself (`model.run()`, `openmc.run()`), its results are kept as is.

  Other `*.py` files without `import openmc` are passed along as helper modules
  (`OPENMC_SCRIPT` names the script when several import `openmc`);
- **XML files**: `model.xml`, or `materials.xml` + `geometry.xml` + `settings.xml`
  [+ `tallies.xml`, `plots.xml`], or one model file of another name (root `<model>`), copied
  to `model.xml` before the run. Give a directory as input to stage XML files together with
  their data (e.g. a multi-group `mgxs.h5`).

**Parameter syntax** (fz defaults):

- variables: `${name}`, with optional default `${name~20}`; `$name` also works where it is
  not followed by a letter, digit or `_`
- formulas: `@{expression}`, e.g. `@{4/3*3.141592653589793*$radius**3}`
- fz context lines: `#@: <python code>` (in Python scripts; in XML, put formulas inline or in
  `<!-- -->` comments)

`$`, `@{`, `#@:` have no meaning in OpenMC inputs. In a Python script, avoid `$word` in
strings (e.g. `os.path.expandvars("$HOME")`): fz would take it for a variable.

#### Example input (`examples/sphere.py`, excerpt)

```python
#@: def volume(r): return 4 / 3 * 3.141592653589793 * r**3
# sphere volume (cm3): @{volume($radius)}
...
sphere = openmc.Sphere(r=${radius~20}, boundary_type="vacuum")
...
settings.particles = ${particles~2000}
...
model.export_to_model_xml()
```

Both examples model a bare sphere of a 2-group multiplying medium in **multi-group mode**:
the cross sections are written by the script (`mgxs.h5`), so they run without any nuclear
data library. `examples/sphere_xml/` is the same model as `model.xml` + `mgxs.h5`.
For continuous-energy models, point OpenMC to a `cross_sections.xml` (see
[Requirements](#requirements)).

### Output

Files read: `openmc.log` (all the output of the Python script and of OpenMC, written by
`OpenMC.sh`; fz's `out.txt` when `openmc.log` is missing or empty, e.g. with a plain
`sh://openmc` calculator) and `tallies.out`.

| Variable | Content |
|---|---|
| `openmc_status` | `NORMAL END`, `ERROR: <first OpenMC error>`, `CRASH: <C++ exception>` (e.g. a malformed XML value), `PYTHON ERROR: <last line of the traceback>` (input script), `NO END BANNER` (interrupted run), `NO OUTPUT` |
| `keff`, `keff_std` | combined k-effective and its standard deviation (eigenvalue mode with enough active batches; empty in fixed-source mode or with a single active batch) |
| `leakage`, `leakage_std` | leakage fraction and its standard deviation |
| `tally`, `tally_std` | for each tally of `tallies.out`, each score: mean (std) as a number, or a list over the filter/nuclide bins in the order of `tallies.out`; flattened by fz into `tally_<id>_<score>`, `tally_std_<id>_<score>` (score names in lowercase, `_` for any other character: `Fission Rate` → `fission_rate`, `(n,gamma)` → `n_gamma`) |

Example (real OpenMC 0.16.0 output of `examples/sphere_xml`, radius 20 cm, 1000 particles):

```
 Combined k-effective        = 1.02059 +/- 0.00834
 Leakage Fraction            = 0.43100 +/- 0.00422
```

```
 =========================>     TALLY 1: FLUX     <=========================

 Incoming Energy [0, 0.625)
   Total Material
     Flux                                 3.11693 +/- 0.0537101
     Fission Rate                         0.311693 +/- 0.00537101
 Incoming Energy [0.625, 20000000)
   Total Material
     Flux                                 19.8263 +/- 0.168332
     Fission Rate                         0.0991315 +/- 0.000841662
```

gives `keff` = 1.02059, `keff_std` = 0.00834, `tally_1_flux` = [3.11693, 19.8263],
`tally_1_fission_rate` = [0.311693, 0.0991315].

Values are read from the terminal output, rounded by OpenMC (`keff` to 5 decimals, tallies
to 6 significant digits). For full precision or anything else (mesh tallies as arrays,
k-generation, source), read the statepoint file with the `openmc` Python API (the files are
in each case directory of the results) with `h5py` or the `openmc` Python API, e.g. by
adding an output to a copy of the model:

```json
"keff_full": "python://__import__('h5py').File(next(base_dir.glob('statepoint.*.h5')))['k_combined'][()].tolist()"
```

`tallies.out` is written by default; it is missing if the model sets
`settings.output = {'tallies': False}`, and then `tally` is empty. With `settings.verbosity`
below 4, the `RESULTS` block is not printed: `openmc_status` is `NO END BANNER` and the
case fails.

### What `NORMAL END` does not tell

`NORMAL END` with a keff and a small standard deviation does not prove that the fission source
converged: check the Shannon entropy (`settings.entropy_mesh`) and enough inactive batches,
especially for loosely coupled systems, and keep the source (`settings.source`) inside the
fissile regions for **all** sampled values of the geometric variables (otherwise:
`ERROR: Exceeded maximum number of source rejections per sample`).

## Requirements

- fz, bash (Git Bash, MSYS2 or WSL on Windows)
- OpenMC (tested with 0.16.0), e.g. `conda install -c conda-forge openmc`
- for continuous-energy models, a nuclear data library (`cross_sections.xml`, see
  [OpenMC data](https://openmc.org/data/)): set `OPENMC_CROSS_SECTIONS`, or
  `materials.cross_sections` in the model

## Installation

```bash
pip install funz-fz
fz install model OpenMC              # or: fz install model https://github.com/Funz/fz-OpenMC
```

```python
import fz
fz.install("OpenMC")
```

Environment of the calculator script (`.fz/calculators/OpenMC.sh`), all optional:

| Variable | Default | Role |
|---|---|---|
| `OPENMC_CMD` | `openmc` on `PATH` | OpenMC executable |
| `OPENMC_PYTHON` | the `python3` next to `OPENMC_CMD` (same conda env), else `python3` on `PATH` | interpreter of Python inputs (needs the `openmc` package) |
| `OPENMC_SCRIPT` | first `*.py` importing `openmc` | Python input to run when several are given |
| `OPENMC_THREADS` | OpenMC default (all cores) | OpenMP threads (`openmc -s N`) |
| `OPENMC_MPI_PROCS` | none | MPI processes (`$OPENMC_MPIEXEC -n N openmc`) |
| `OPENMC_MPIEXEC` | `mpiexec` | MPI launcher |
| `OPENMC_OPTS` | none | extra `openmc` options, appended as given (e.g. `--event`) |
| `OPENMC_CROSS_SECTIONS` | none | read by OpenMC: `cross_sections.xml` used when the model sets none |

`OPENMC_CMD`'s directory is put first on `PATH` while a Python input runs, so `model.run()`
uses the same OpenMC. The threads/MPI settings do not apply when the script runs OpenMC
itself: pass them to `model.run(threads=..., mpi_args=[...])`.

Exit codes: 0 normal end, 1 no input found (or a Python input that neither ran OpenMC nor
exported the model), 2 usage, 3 Python input failed, 4 executable not found, 5 OpenMC failed
(message on stderr), 6 no `RESULTS` banner or no statepoint (interrupted run).

## Usage

```python
import fz

results = fz.fzr(
    "examples/sphere.py",
    {"radius": [15, 20, 25]},          # sphere radius (cm)
    "OpenMC",
    calculators="localhost_OpenMC",    # optional: found automatically
    results_dir="results",
)
print(results[["radius", "status", "openmc_status", "keff", "keff_std"]])
```

```
   radius status openmc_status     keff  keff_std
0      15   done    NORMAL END  0.77852   0.00547
1      20   done    NORMAL END  1.01483   0.00496
2      25   done    NORMAL END  1.19395   0.00714
```

Same with the CLI:

```bash
fzr --input_path examples/sphere_xml --model OpenMC \
    --input_variables '{"radius": [15, 20, 25]}' --results_dir results --format json
```

Other entry points: `fz.fzi("examples/sphere.py", "OpenMC")` (variables),
`fz.fzc(..., output_dir="compiled")` (compiled inputs), `fz.fzo("results/*", "OpenMC")`
(re-parse outputs), and `fz.fzd` for design of experiments or optimization, e.g. the critical
radius (`keff` = 1) with the [brent](https://github.com/Funz/fz-brent) root-finding algorithm
(written in R: needs R and `rpy2`):

```python
fz.install_algorithm("brent")
analysis = fz.fzd("examples/sphere.py", {"radius": "[15;25]"}, "OpenMC",
                  output_expression="keff", algorithm="brent",
                  algorithm_options={"ytarget": 1.0, "xtol": 0.1})
```

Keep the tolerances above the Monte Carlo noise (here σ(keff) ≈ 0.005 ↔ ≈ 0.1 cm of radius
with 2000 particles per batch). For this example, the critical radius is ≈ 19.4 cm (found
with a 1D minimization of `(keff - 1)**2` over [15, 25] cm).

Remote execution: give an `ssh://` or `slurm://` calculator running
`bash .fz/calculators/OpenMC.sh` on a host where OpenMC is installed (see the
[fz calculators documentation](https://github.com/Funz/fz/blob/main/doc/calculators.md));
results can be reused with a `cache://<previous results dir>` calculator placed first.

## Repository layout

```
fz-OpenMC/
├── .fz/
│   ├── models/OpenMC.json              # syntax and output extraction (generated)
│   └── calculators/
│       ├── OpenMC.sh                   # runs the Python input and/or openmc, checks the end
│       └── localhost_OpenMC.json       # local calculator alias
├── examples/
│   ├── sphere.py                       # parameterized Python input (multi-group)
│   └── sphere_xml/                     # same model as model.xml + mgxs.h5
├── scripts/make_model.py               # writes .fz/models/OpenMC.json
└── tests/
    ├── test_plugin.py                  # structure, fzi/fzc
    ├── test_calculator.py              # OpenMC.sh with a fake openmc
    ├── test_outputs.py                 # output extraction on reference outputs
    ├── test_fz_e2e.py                  # fzr end to end (fake openmc; real OpenMC if installed)
    ├── make_fixtures.sh                # regenerates fixtures/ with a real OpenMC
    └── fixtures/                       # real OpenMC 0.16.0 outputs (ok_*, err_*)
```

The output expressions are one-line `python://` lambdas: edit `scripts/make_model.py`, then
run `python scripts/make_model.py` (`tests/test_outputs.py` checks that the JSON is up to date).

## Tests

```bash
pip install funz-fz pytest
pytest tests/                        # no OpenMC needed (real-OpenMC tests are skipped)
OPENMC_CMD=$(which openmc) pytest tests/   # also fzr runs with a real OpenMC
OPENMC_CMD=$(which openmc) bash tests/make_fixtures.sh   # regenerate the reference outputs
```

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `OpenMC executable not found` (exit 4) | set `OPENMC_CMD`, or put `openmc` on `PATH` (activate its conda env) |
| `PYTHON ERROR: ModuleNotFoundError: No module named 'openmc'` | the Python found has no `openmc` package: set `OPENMC_PYTHON` |
| `ERROR: No cross_sections.xml file was specified ...` | set `OPENMC_CROSS_SECTIONS` or `materials.cross_sections` |
| `ERROR: Cross section HDF5 file '...' does not exist` | relative data path: give the data file with the input (input directory) or an absolute path |
| `CRASH: stoll` | a non-numeric value in an integer XML field (e.g. `<particles>`) |
| `ERROR: Exceeded maximum number of source rejections per sample ...` | source outside the fissile (or any) region for these variable values |
| `NO END BANNER` | run killed, or `settings.verbosity` < 4, or `model.run(output=False)` in a Python input (the output must reach `openmc.log`) |
| `keff` empty with `NORMAL END` | fixed-source mode, or a single active batch |

## License

BSD 3-Clause, see [LICENSE](LICENSE).

## Related projects

- [fz](https://github.com/Funz/fz): parametric computing framework
- [fz-MCNP](https://github.com/Funz/fz-MCNP), [fz-Serpent](https://github.com/Funz/fz-Serpent),
  [fz-Moret](https://github.com/Funz/fz-Moret): other Monte Carlo transport codes
