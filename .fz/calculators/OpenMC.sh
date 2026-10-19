#!/bin/bash
# OpenMC calculator script for fz
#
# Runs OpenMC in the case directory, on either input form:
#   - a Python script (*.py importing openmc): run with OPENMC_PYTHON; if the
#     script only exports the model (model.export_to_model_xml() or
#     export_to_xml()), OpenMC is then run on the exported XML; if the script
#     runs OpenMC itself (model.run()), its statepoint is kept as is;
#   - XML input: model.xml, or materials.xml + geometry.xml + settings.xml
#     [+ tallies.xml ...], or a single model file <name>.xml (<model> root),
#     copied to model.xml.
# All the output (Python script and OpenMC) goes to openmc.log, parsed by the
# OpenMC model together with tallies.out.
#
# Environment (all optional):
#   OPENMC_CMD             OpenMC executable (default: openmc on PATH)
#   OPENMC_PYTHON          Python interpreter for *.py inputs (default: the python3
#                          next to OPENMC_CMD, e.g. in the same conda env, else
#                          python3 on PATH)
#   OPENMC_SCRIPT          name of the Python script to run when several *.py files
#                          are given (default: the first *.py file importing openmc)
#   OPENMC_THREADS         number of OpenMP threads (openmc -s N)
#   OPENMC_MPI_PROCS       number of MPI processes (OPENMC_MPIEXEC -n N openmc)
#   OPENMC_MPIEXEC         MPI launcher (default: mpiexec)
#   OPENMC_OPTS            extra openmc command-line options, appended as given
#   OPENMC_CROSS_SECTIONS  cross_sections.xml (continuous energy) or MGXS HDF5 file
#                          used when the materials do not set one (read by OpenMC)
#
# Exit codes:
#   0 normal end (RESULTS banner in openmc.log)
#   1 no input found           2 usage
#   3 Python script failed     4 executable not found
#   5 OpenMC failed (non-zero exit code; message on stderr)
#   6 no RESULTS banner or no statepoint (interrupted or crashed run)

if [ $# -eq 0 ]; then
  echo "Usage: $0 <input file ...|input_directory>" >&2
  exit 2
fi
if [ $# -eq 1 ] && [ -d "$1" ]; then
  cd "$1" || exit 1
  set -- *
fi

# Executable
OPENMC_CMD="${OPENMC_CMD:-$(command -v openmc 2>/dev/null)}"
if [ -z "$OPENMC_CMD" ] || ! command -v "$OPENMC_CMD" >/dev/null 2>&1; then
  echo "OpenMC executable not found${OPENMC_CMD:+: $OPENMC_CMD} (set OPENMC_CMD or put openmc on PATH)" >&2
  exit 4
fi
OPENMC_CMD="$(command -v "$OPENMC_CMD")"

# Input: a Python script, else XML files
SCRIPT=""
if [ -n "${OPENMC_SCRIPT:-}" ]; then
  [ -f "$OPENMC_SCRIPT" ] || { echo "OPENMC_SCRIPT not found: $OPENMC_SCRIPT" >&2; exit 1; }
  SCRIPT="$OPENMC_SCRIPT"
else
  for f in "$@"; do
    case "$f" in
      *.py) [ -f "$f" ] && grep -q -E '^[[:space:]]*(import|from)[[:space:]]+openmc' "$f" && { SCRIPT="$f"; break; } ;;
    esac
  done
fi
MODEL=""
if [ -z "$SCRIPT" ]; then
  for f in "$@"; do
    case "$f" in
      materials.xml|geometry.xml|settings.xml|tallies.xml|plots.xml|cross_sections.xml) ;;
      *.xml) [ -f "$f" ] && grep -q '<model' "$f" && { MODEL="$f"; break; } ;;
    esac
  done
  # openmc <file> resolves relative paths of the model (cross_sections, ...)
  # against "<file>/": run it on ./model.xml instead
  if [ -n "$MODEL" ] && [ "$MODEL" != model.xml ] && [ "$MODEL" != ./model.xml ]; then
    if [ -e model.xml ] && ! cmp -s "$MODEL" model.xml; then
      echo "Both $MODEL and model.xml given: ambiguous model" >&2
      exit 1
    fi
    cp "$MODEL" model.xml
  fi
  if [ ! -f model.xml ] && [ ! -f settings.xml ]; then
    echo "No OpenMC input found in: $* (expected a Python script importing openmc, model.xml or settings.xml)" >&2
    exit 1
  fi
fi

# Stale outputs would be parsed instead of the new ones
rm -f statepoint.*.h5 summary.h5 tallies.out openmc.log

run_bg() {
  "$@" >> openmc.log 2>&1 &
  local pid=$!
  echo $pid >> PID   # lets fz kill the run on interrupt
  wait $pid
  local rc=$?
  rm -f PID
  return $rc
}

if [ -n "$SCRIPT" ]; then
  if [ -z "${OPENMC_PYTHON:-}" ]; then
    OPENMC_PYTHON="$(dirname "$OPENMC_CMD")/python3"
    [ -x "$OPENMC_PYTHON" ] || OPENMC_PYTHON="$(command -v python3 2>/dev/null || command -v python 2>/dev/null)"
  fi
  # model.run() inside the script finds the same openmc
  export PATH="$(dirname "$OPENMC_CMD"):$PATH"
  run_bg "$OPENMC_PYTHON" "$SCRIPT"
  RC=$?
  if [ $RC -ne 0 ]; then
    echo "Python script $SCRIPT failed (exit code $RC):" >&2
    tail -n 5 openmc.log >&2
    exit 3
  fi
fi

if ! ls statepoint.*.h5 >/dev/null 2>&1; then
  if [ -n "$SCRIPT" ] && [ ! -f model.xml ] && [ ! -f settings.xml ]; then
    echo "Python script $SCRIPT neither ran OpenMC nor exported model.xml/settings.xml" >&2
    exit 1
  fi
  OPTS=""
  [ -n "${OPENMC_THREADS:-}" ] && OPTS="-s $OPENMC_THREADS"
  if [ -n "${OPENMC_MPI_PROCS:-}" ]; then
    run_bg ${OPENMC_MPIEXEC:-mpiexec} -n "$OPENMC_MPI_PROCS" "$OPENMC_CMD" $OPTS ${OPENMC_OPTS:-}
  else
    run_bg "$OPENMC_CMD" $OPTS ${OPENMC_OPTS:-}
  fi
  RC=$?
  if [ $RC -ne 0 ]; then
    echo "OpenMC failed (exit code $RC):" >&2
    grep -m1 -A3 -E '^ ERROR:|what\(\):' openmc.log >&2 || tail -n 5 openmc.log >&2
    exit 5
  fi
fi

if ! grep -q -E '^ =+> +RESULTS +<=+' openmc.log || ! ls statepoint.*.h5 >/dev/null 2>&1; then
  echo "No RESULTS banner or no statepoint file: run interrupted or crashed (see openmc.log)" >&2
  exit 6
fi
grep -E '^ (Combined k-effective|Leakage Fraction) ' openmc.log
exit 0
