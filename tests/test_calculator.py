"""Tests of .fz/calculators/OpenMC.sh with fake openmc and python executables.

The fake openmc records its arguments and working directory, then replays the
reference outputs of tests/fixtures/$FAKE_CASE (terminal output, tallies.out,
a statepoint file) and exits with $FAKE_RC (OpenMC exits with 255 after an
"ERROR:", 134 after an uncaught C++ exception).

Run: pytest tests/test_calculator.py
"""

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".fz" / "calculators" / "OpenMC.sh"
FIXTURES = ROOT / "tests" / "fixtures"

FAKE_OPENMC = """#!/bin/bash
printf '%s\\n' "$@" > "$(dirname "$0")/args.txt"
pwd > "$(dirname "$0")/cwd.txt"
echo call >> "$(dirname "$0")/calls.txt"
ls > "$(dirname "$0")/files.txt"
[ -n "$FAKE_SLEEP" ] && sleep "$FAKE_SLEEP"
case "$FAKE_CASE" in
  none) exit ${FAKE_RC:-0} ;;
esac
cat "$FIXTURES/$FAKE_CASE/openmc.log"
if [ "${FAKE_RC:-0}" -eq 0 ]; then
  [ -f "$FIXTURES/$FAKE_CASE/tallies.out" ] && cp "$FIXTURES/$FAKE_CASE/tallies.out" .
  touch statepoint.30.h5 summary.h5
fi
exit ${FAKE_RC:-0}
"""

# Stands for a Python with openmc: export (or run, with FAKE_SCRIPT_RUNS) the model
FAKE_PYTHON = """#!/bin/bash
echo "$@" > "$(dirname "$0")/python_args.txt"
echo "PATH=$PATH" > "$(dirname "$0")/python_env.txt"
grep -q RAISE "$1" && { cat "$FIXTURES/err_python/openmc.log"; exit 1; }
if [ -n "$FAKE_SCRIPT_RUNS" ]; then
  openmc
  exit $?
fi
echo '<model/>' > model.xml
"""

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="bash required")


@pytest.fixture
def bindir(tmp_path):
    d = tmp_path / "bin"
    d.mkdir()
    for name, text in (("openmc", FAKE_OPENMC), ("python3", FAKE_PYTHON)):
        (d / name).write_text(text)
        (d / name).chmod(0o755)
    return d


@pytest.fixture
def run(tmp_path, bindir):
    case_dir = tmp_path / "case"
    case_dir.mkdir()

    def _run(fake_case="ok_eigenvalue", files=("model.xml", "mgxs.h5"), env=None, args=None,
             use_cmd=True):
        for name in files:
            content = "<model>\n</model>\n" if name.endswith(".xml") else "import openmc\n"
            path = case_dir / name
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.write_text(content)
        full_env = dict(os.environ, FAKE_CASE=fake_case, FIXTURES=str(FIXTURES))
        for k in list(full_env):
            if k.startswith("OPENMC_") or k.startswith("FAKE_") and k != "FAKE_CASE":
                full_env.pop(k)
        if use_cmd:
            full_env["OPENMC_CMD"] = str(bindir / "openmc")
        full_env.update(env or {})
        proc = subprocess.run(["bash", str(SCRIPT), *(args if args is not None else files)],
                              cwd=case_dir, env=full_env, capture_output=True, text=True)
        return proc, case_dir

    return _run


def args_of(bindir):
    return (bindir / "args.txt").read_text().split()


def test_usage(run):
    proc, _ = run(args=[])
    assert proc.returncode == 2


def test_executable_not_found(run, tmp_path):
    proc, _ = run(env={"OPENMC_CMD": str(tmp_path / "nowhere" / "openmc")})
    assert proc.returncode == 4
    assert "OpenMC executable not found" in proc.stderr


def test_openmc_on_path(run, bindir):
    proc, _ = run(use_cmd=False, env={"PATH": f"{bindir}:{os.environ['PATH']}"})
    assert proc.returncode == 0, proc.stderr


def test_no_input(run):
    proc, _ = run(files=("notes.txt",))
    assert proc.returncode == 1
    assert "No OpenMC input found" in proc.stderr


def test_xml_model(run, bindir):
    proc, case = run()
    assert proc.returncode == 0, proc.stderr
    assert args_of(bindir) == []          # openmc run in the case directory
    assert Path((bindir / "cwd.txt").read_text().strip()) == case
    assert (case / "openmc.log").read_text() == (FIXTURES / "ok_eigenvalue" / "openmc.log").read_text()
    assert "Combined k-effective        = 1.02059 +/- 0.00834" in proc.stdout


def test_separate_xml_files(run, bindir):
    proc, _ = run(files=("materials.xml", "geometry.xml", "settings.xml", "tallies.xml"))
    assert proc.returncode == 0, proc.stderr
    assert args_of(bindir) == []


def test_model_file_with_other_name_is_copied_to_model_xml(run, bindir):
    """openmc <file> would resolve relative paths of the model against "<file>/"."""
    proc, case = run(files=("pincell.xml", "mgxs.h5"))
    assert proc.returncode == 0, proc.stderr
    assert args_of(bindir) == []
    assert "model.xml" in (bindir / "files.txt").read_text().split()
    assert (case / "model.xml").read_text() == (case / "pincell.xml").read_text()


def test_ambiguous_models(run):
    _, case = run(fake_case="none", files=())
    (case / "model.xml").write_text("<model><!-- other --></model>\n")
    proc, _ = run(files=("pincell.xml", "model.xml"), args=["pincell.xml"])
    assert proc.returncode == 1
    assert "ambiguous" in proc.stderr


def test_rerun_with_copied_model(run):
    """A second run in the same directory finds the model.xml copied by the first one."""
    proc, _ = run(files=("pincell.xml", "mgxs.h5"))
    assert proc.returncode == 0, proc.stderr
    proc, _ = run(files=("pincell.xml", "mgxs.h5"))
    assert proc.returncode == 0, proc.stderr


def test_input_directory(run, bindir):
    proc, case = run(files=("deck/model.xml", "deck/mgxs.h5"), args=["deck"])
    assert proc.returncode == 0, proc.stderr
    assert Path((bindir / "cwd.txt").read_text().strip()) == case / "deck"


def test_threads_mpi_and_options(run, bindir):
    mpiexec = bindir / "mpiexec"
    mpiexec.write_text('#!/bin/bash\nprintf "%s\\n" "$@" > "$(dirname "$0")/mpi_args.txt"\nshift 2\nexec "$@"\n')
    mpiexec.chmod(0o755)
    proc, _ = run(env={"OPENMC_THREADS": "4", "OPENMC_MPI_PROCS": "2",
                       "OPENMC_MPIEXEC": str(mpiexec), "OPENMC_OPTS": "--event"})
    assert proc.returncode == 0, proc.stderr
    assert (bindir / "mpi_args.txt").read_text().split()[:2] == ["-n", "2"]
    assert args_of(bindir) == ["-s", "4", "--event"]


def test_stale_outputs_are_removed(run, bindir):
    _, case = run(fake_case="none", files=())
    for f in ("statepoint.10.h5", "summary.h5", "tallies.out", "openmc.log"):
        (case / f).write_text("old")
    proc, case = run(fake_case="none")
    assert proc.returncode == 6          # no RESULTS banner and no statepoint
    assert not (case / "statepoint.10.h5").exists()
    assert not (case / "tallies.out").exists()


@pytest.mark.parametrize("fake_case, fake_rc", [("err_xs_missing", 255), ("err_bad_value", 134)])
def test_openmc_failure(run, fake_case, fake_rc):
    proc, case = run(fake_case=fake_case, env={"FAKE_RC": str(fake_rc)})
    assert proc.returncode == 5
    assert f"exit code {fake_rc}" in proc.stderr
    first = (FIXTURES / fake_case / "stderr.txt").read_text().splitlines()[-1].strip()
    assert first.split()[0] in proc.stderr
    assert not (case / "PID").exists()


def test_interrupted_run(run):
    """Exit code 0 but no RESULTS banner (e.g. killed MPI rank)."""
    proc, _ = run(fake_case="none")
    assert proc.returncode == 6


def test_python_script_exporting_xml(run, bindir):
    proc, case = run(files=("sphere.py",))
    assert proc.returncode == 0, proc.stderr
    # the python3 next to OPENMC_CMD (same environment as openmc)
    assert (bindir / "python_args.txt").read_text().split() == ["sphere.py"]
    assert args_of(bindir) == []
    assert (case / "model.xml").exists()


def test_python_script_running_openmc(run, bindir):
    """model.run() in the script: the statepoint exists, openmc is not run again."""
    proc, case = run(files=("sphere.py",), env={"FAKE_SCRIPT_RUNS": "1"})
    assert proc.returncode == 0, proc.stderr
    # OPENMC_CMD's directory first on PATH, so that model.run() finds the same openmc
    assert (bindir / "python_env.txt").read_text().split(":")[0] == f"PATH={bindir}"
    assert (bindir / "calls.txt").read_text().split() == ["call"]
    assert "Combined k-effective" in (case / "openmc.log").read_text()


def test_python_script_choice(run, bindir):
    """Helper modules without 'import openmc' are skipped; OPENMC_SCRIPT forces the choice."""
    (run(fake_case="none", files=())[1] / "helpers.py").write_text("X = 1\n")
    proc, _ = run(files=("helpers.py", "sphere.py"))
    assert proc.returncode == 0, proc.stderr
    assert (bindir / "python_args.txt").read_text().split() == ["sphere.py"]
    proc, _ = run(files=("helpers.py", "sphere.py", "other.py"), env={"OPENMC_SCRIPT": "other.py"})
    assert (bindir / "python_args.txt").read_text().split() == ["other.py"]


def test_python_script_failure(run):
    _, case = run(fake_case="none", files=())
    (case / "sphere.py").write_text("import openmc\nRAISE\n")
    proc, _ = run(files=("sphere.py",))
    assert proc.returncode == 3
    assert "AttributeError" in proc.stderr


def test_python_script_without_model(run, bindir):
    _, case = run(fake_case="none", files=())
    (case / "sphere.py").write_text("import openmc\n")
    proc, _ = run(files=("sphere.py",), env={"OPENMC_PYTHON": "true"})
    assert proc.returncode == 1
    assert "neither ran OpenMC nor exported" in proc.stderr


def test_pid_file(run, bindir):
    """The PID of the running process is written to PID (fz kills it on interrupt)."""
    _, case = run(fake_case="none", files=())
    (case / "model.xml").write_text("<model/>\n")
    env = dict(os.environ, FAKE_CASE="ok_eigenvalue", FIXTURES=str(FIXTURES), FAKE_SLEEP="2",
               OPENMC_CMD=str(bindir / "openmc"))
    proc = subprocess.Popen(["bash", str(SCRIPT), "model.xml"], cwd=case, env=env)
    for _ in range(50):
        if (case / "PID").exists() and (case / "PID").read_text().strip():
            break
        time.sleep(0.05)
    pid = int((case / "PID").read_text().split()[0])
    os.kill(pid, 0)                       # alive
    assert proc.wait(timeout=30) == 0
    assert not (case / "PID").exists()
