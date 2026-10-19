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
# Exit codes (on failure, the first line of stderr is the error message):
#   0 normal end (RESULTS banner in openmc.log); stdout: keff, leakage and the
#     path of the last statepoint
#   1 no input found           2 usage
#   3 Python script failed (Python error, not in OpenMC)
#   4 executable not found
#   5 OpenMC failed, run directly or by model.run() in the Python script
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

# First OpenMC error of openmc.log on one line: " ERROR: <message>" and its
# continuation lines, else an uncaught C++ exception ("what(): ..."). With
# several threads, the message may be printed once per thread, the copies
# interleaved or glued: same rule as the openmc_status output of the model
# (scripts/make_model.py): pieces cut at "ERROR:", at runs of 2 blanks or more
# and at the copies of the first piece, each kept once.
openmc_error() {
  awk '
    function add(y) { gsub(/^ +| +$/, "", y); if (y != "" && !seen[y]++) msg = msg (msg == "" ? "" : " ") y }
    !on && /^ ERROR: / { on = 1 }
    on && (/^Traceback / || /^\[/ || /^ =+> / || /^ *WARNING: /) { exit }
    on {
      sub(/Abort\(.*/, "")
      n = split($0, piece, /ERROR:|[[:space:]][[:space:]]+/)
      for (i = 1; i <= n; i++) {
        x = piece[i]; gsub(/[[:space:]]+/, " ", x); sub(/^ /, "", x); sub(/ $/, "", x)
        if (x != "") p[++np] = x
      }
    }
    END {
      for (i = 1; i <= np; i++) {
        x = p[i]
        while ((k = index(x, p[1])) > 0) { add(substr(x, 1, k - 1)); add(p[1]); x = substr(x, k + length(p[1])) }
        add(x)
      }
      if (msg != "") print msg
    }' openmc.log
  grep -q '^ ERROR: ' openmc.log && return 0
  local what
  what="$(sed -n -E 's/^ +what\(\): +//p' openmc.log | head -n 1)"
  [ -n "$what" ] && { echo "$what"; return 0; }
  return 1
}

# Last line of the Python traceback, with the line of the script that failed
python_error() {
  local msg at
  msg="$(awk '/^Traceback \(most recent call last\):/ { tb = 1; next } tb && /^[^ \t]/ { last = $0 } END { print last }' openmc.log)"
  at="$(sed -n -E "s/^ +File \"(.*\/)?${SCRIPT//./\\.}\", line ([0-9]+).*/\2/p" openmc.log | tail -n 1)"
  echo "${at:+line $at: }${msg:-$(tail -n 1 openmc.log)}"
}

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
    # model.run() raises RuntimeError after an OpenMC error: an OpenMC failure
    if MSG="$(openmc_error)"; then
      echo "OpenMC failed in $SCRIPT (exit code $RC): $MSG" >&2
      exit 5
    fi
    echo "Python script $SCRIPT failed (exit code $RC): $(python_error)" >&2
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
    echo "OpenMC failed (exit code $RC): $(openmc_error || tail -n 1 openmc.log)" >&2
    exit 5
  fi
fi

if ! grep -q -E '^ =+> +RESULTS +<=+' openmc.log || ! ls statepoint.*.h5 >/dev/null 2>&1; then
  if MSG="$(openmc_error)"; then
    echo "OpenMC failed: $MSG" >&2
  elif ! ls statepoint.*.h5 >/dev/null 2>&1; then
    echo "No statepoint file: run interrupted or crashed (see openmc.log)" >&2
  else
    echo "No RESULTS banner: run interrupted, or settings.verbosity < 4 (see openmc.log)" >&2
  fi
  exit 6
fi
grep -E '^ (Combined k-effective|Leakage Fraction) ' openmc.log
# last statepoint (highest batch number; names are zero-padded with triggers)
SP="$(ls statepoint.*.h5 | sed -E 's/^statepoint\.0*([0-9]+)\.h5$/\1 &/' | sort -n | tail -n 1 | cut -d' ' -f2)"
echo "Statepoint: $PWD/$SP"
exit 0
