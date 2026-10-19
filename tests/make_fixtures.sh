#!/bin/bash
# Regenerates tests/fixtures/<case>/ with a real OpenMC, through OpenMC.sh:
# openmc.log, tallies.out (when written), rc (exit code of OpenMC.sh) and
# stderr.txt (its messages), for the output-extraction and calculator tests.
#
# Usage: OPENMC_CMD=/path/to/openmc bash tests/make_fixtures.sh
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUNNER="$ROOT/.fz/calculators/OpenMC.sh"
FIX="$ROOT/tests/fixtures"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# make_case <name> <sed script for model.xml | -> [python script]
make_case() {
  local name="$1" sedexpr="$2" script="${3:-}"
  local d="$WORK/$name"
  mkdir -p "$d"
  if [ -n "$script" ]; then
    sed -e 's/\${radius~20}/20/; s/\${particles~2000}/1000/; s/@{volume(\$radius)}/33510.3/' \
      "$ROOT/examples/sphere.py" > "$d/sphere.py"
    [ "$sedexpr" != - ] && sed -i -e "$sedexpr" "$d/sphere.py"
    args=(sphere.py)
  else
    sed -e 's/\${radius~20}/20/; s/\${particles~2000}/1000/; s/@{[^}]*}/33510.3/' \
      "$ROOT/examples/sphere_xml/model.xml" > "$d/model.xml"
    [ "$sedexpr" != - ] && sed -i -e "$sedexpr" "$d/model.xml"
    cp "$ROOT/examples/sphere_xml/mgxs.h5" "$d/"
    args=(model.xml mgxs.h5)
  fi
  (cd "$d" && bash "$RUNNER" "${args[@]}" > stdout.txt 2> stderr.txt; echo $? > rc)
  rm -rf "${FIX:?}/$name"
  mkdir -p "$FIX/$name"
  for f in openmc.log tallies.out rc stderr.txt; do
    [ -f "$d/$f" ] && cp "$d/$f" "$FIX/$name/"
  done
  # the fixtures must not depend on the machine: drop absolute paths
  sed -i -e "s#$d#<case>#g; s#$ROOT#<root>#g; s#[^ \"']*/site-packages/#<site-packages>/#g" "$FIX/$name"/*
  echo "$name: rc=$(cat "$d/rc")"
}

make_case ok_eigenvalue -
make_case ok_fixed_source 's#<run_mode>eigenvalue</run_mode>#<run_mode>fixed source</run_mode>#; s#0.0 0.0 0.0 20"#0.0 0.0 0.0 5"#'
make_case ok_python - python
make_case ok_python_run 's/^model.export_to_model_xml().*/model.run()/' python
make_case ok_one_active_batch 's#<batches>30</batches>#<batches>11</batches>#'
make_case err_xs_missing 's#<cross_sections>mgxs.h5</cross_sections>#<cross_sections>nofile.h5</cross_sections>#'
make_case err_bad_value 's#<particles>1000</particles>#<particles>abc</particles>#'
make_case err_source_outside 's#<parameters>0.0 0.0 0.0</parameters>#<parameters>100.0 0.0 0.0</parameters>#'
make_case err_python 's/openmc.Sphere(/openmc.Sphre(/' python
make_case err_python_run 's/^model.export_to_model_xml().*/model.materials.cross_sections = "nofile.h5"; model.run()/' python
