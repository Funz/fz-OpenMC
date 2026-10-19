"""Structure of the fz-OpenMC plugin: model and calculator files, variables
and compilation of the examples (fzi, fzc).

Run: pytest tests/test_plugin.py
"""

import json
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODEL_FILE = ROOT / ".fz" / "models" / "OpenMC.json"
CALCULATOR = ROOT / ".fz" / "calculators" / "localhost_OpenMC.json"
SCRIPT = ROOT / ".fz" / "calculators" / "OpenMC.sh"
OUTPUTS = ["openmc_status", "keff", "keff_std", "leakage", "leakage_std", "tally", "tally_std"]


def test_model_file():
    model = json.loads(MODEL_FILE.read_text())
    assert model["id"] == "OpenMC" == MODEL_FILE.stem
    for field in ("varprefix", "formulaprefix", "delim", "commentline"):
        assert field in model
    assert list(model["output"]) == OUTPUTS
    # native Python extraction: no bash/grep/awk needed to parse outputs (Windows)
    for name, cmd in model["output"].items():
        assert cmd.startswith("python://"), name


def test_calculator_file():
    calc = json.loads(CALCULATOR.read_text())
    assert calc["uri"] == "sh://"
    assert calc["models"] == {"OpenMC": "bash .fz/calculators/OpenMC.sh"}


def test_script_is_executable():
    assert os.access(SCRIPT, os.X_OK)


fz = pytest.importorskip("fz")


@pytest.mark.parametrize("example", ["sphere.py", "sphere_xml"])
def test_fzi(example):
    variables = fz.fzi(str(ROOT / "examples" / example), "OpenMC")
    assert variables["radius"] == 20
    assert variables["particles"] == 2000


@pytest.mark.parametrize("example, compiled, expected", [
    ("sphere.py", "sphere.py", ["openmc.Sphere(r=12.5,", "settings.particles = 500",
                                "# sphere volume (cm3): 8181.230868723419"]),
    ("sphere_xml", "model.xml", ['coeffs="0.0 0.0 0.0 12.5"', "<particles>500</particles>",
                                 "sphere volume (cm3): 8181.230868723419 -->"]),
])
def test_fzc(tmp_path, example, compiled, expected):
    fz.fzc(str(ROOT / "examples" / example), {"radius": 12.5, "particles": 500}, "OpenMC",
           output_dir=str(tmp_path))
    files = list(tmp_path.rglob(compiled))
    assert len(files) == 1
    text = files[0].read_text()
    for snippet in expected:
        assert snippet in text
    assert "${" not in text and "$radius" not in text and "@{" not in text
    if example == "sphere_xml":
        # the binary cross-section file is copied unchanged
        mgxs = files[0].parent / "mgxs.h5"
        assert mgxs.read_bytes() == (ROOT / "examples" / "sphere_xml" / "mgxs.h5").read_bytes()
