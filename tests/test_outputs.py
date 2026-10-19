"""Output extraction of the OpenMC model on real OpenMC 0.16.0 outputs.

tests/fixtures/<case>/ holds the openmc.log and tallies.out written by
OpenMC.sh with a real OpenMC (regenerate with tests/make_fixtures.sh).

Run: pytest tests/test_outputs.py
"""

import json
import shutil
from pathlib import Path

import pytest

fz_outparsers = pytest.importorskip("fz.outparsers")

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
MODEL = json.loads((ROOT / ".fz" / "models" / "OpenMC.json").read_text())

SPHERE_TALLY = {"1": {"flux": [3.11693, 19.8263], "fission_rate": [0.311693, 0.0991315]},
                "2": {"absorption_rate": 0.572295}}
SPHERE_TALLY_STD = {"1": {"flux": [0.0537101, 0.168332], "fission_rate": [0.00537101, 0.000841662]},
                    "2": {"absorption_rate": 0.00591116}}

EXPECTED = {
    "ok_eigenvalue": {"openmc_status": "NORMAL END", "keff": 1.02059, "keff_std": 0.00834,
                      "leakage": 0.431, "leakage_std": 0.00422,
                      "tally": SPHERE_TALLY, "tally_std": SPHERE_TALLY_STD},
    # same model, written by a Python script, run by OpenMC.sh or by model.run()
    "ok_python": {"openmc_status": "NORMAL END", "keff": 1.02059, "keff_std": 0.00834,
                  "tally": SPHERE_TALLY},
    "ok_python_run": {"openmc_status": "NORMAL END", "keff": 1.02059, "keff_std": 0.00834,
                      "tally": SPHERE_TALLY},
    "ok_fixed_source": {"openmc_status": "NORMAL END", "keff": None, "keff_std": None,
                        "leakage": 1.1381, "leakage_std": 0.00384,
                        "tally": {"1": {"flux": [0.883108, 8.47423],
                                        "fission_rate": [0.0883108, 0.0423711]},
                                  "2": {"absorption_rate": 0.190715}}},
    # a single active batch: no combined keff, no uncertainty
    "ok_one_active_batch": {"openmc_status": "NORMAL END", "keff": None, "keff_std": None,
                            "leakage": 0.432, "leakage_std": None},
    "err_xs_missing": {"openmc_status": "ERROR: Cross section HDF5 file 'nofile.h5' does not exist",
                       "keff": None, "tally": {}, "tally_std": {}},
    # message wrapped by OpenMC on two lines
    "err_source_outside": {"openmc_status": "ERROR: Exceeded maximum number of source rejections "
                                            "per sample. Please check your source definition.",
                           "keff": None},
    "err_bad_value": {"openmc_status": "CRASH: stoll", "keff": None},
    "err_python": {"openmc_status": "PYTHON ERROR: AttributeError: module 'openmc' has no "
                                    "attribute 'Sphre'. Did you mean: 'Sphere'?"},
    # model.run() failure: the OpenMC error comes first
    "err_python_run": {"openmc_status": "ERROR: Cross section HDF5 file '<case>/nofile.h5' "
                                        "does not exist"},
}


def evaluate(directory, name):
    return fz_outparsers.evaluate_python_output(MODEL["output"][name], directory)


def test_every_fixture_is_checked():
    assert sorted(p.name for p in FIXTURES.iterdir() if p.is_dir()) == sorted(EXPECTED)


@pytest.mark.parametrize("case", sorted(EXPECTED))
def test_fixture(case):
    for name, expected in EXPECTED[case].items():
        assert evaluate(FIXTURES / case, name) == expected, name


def test_no_output(tmp_path):
    assert evaluate(tmp_path, "openmc_status") == "NO OUTPUT"
    for name in ("keff", "keff_std", "leakage", "leakage_std"):
        assert evaluate(tmp_path, name) is None
    assert evaluate(tmp_path, "tally") == {}


def test_empty_log_falls_back_to_out_txt(tmp_path):
    """A run with a plain sh://openmc calculator has its output in fz's out.txt."""
    (tmp_path / "openmc.log").write_text("")
    shutil.copy(FIXTURES / "ok_eigenvalue" / "openmc.log", tmp_path / "out.txt")
    assert evaluate(tmp_path, "openmc_status") == "NORMAL END"
    assert evaluate(tmp_path, "keff") == 1.02059


def test_interrupted_run(tmp_path):
    text = (FIXTURES / "ok_eigenvalue" / "openmc.log").read_text()
    (tmp_path / "openmc.log").write_text(text[:text.index("RESULTS")].rsplit("\n", 1)[0])
    assert evaluate(tmp_path, "openmc_status") == "NO END BANNER"
    assert evaluate(tmp_path, "keff") is None


def test_crlf(tmp_path):
    for f in ("openmc.log", "tallies.out"):
        data = (FIXTURES / "ok_eigenvalue" / f).read_text()
        (tmp_path / f).write_bytes(data.replace("\n", "\r\n").encode())
    assert evaluate(tmp_path, "openmc_status") == "NORMAL END"
    assert evaluate(tmp_path, "keff_std") == 0.00834
    assert evaluate(tmp_path, "tally") == SPHERE_TALLY


def test_tallies_with_nuclides_and_long_scores(tmp_path):
    """Layout of tallies.out with cell/nuclide bins and a score name of 36
    characters or more (followed by a single blank)."""
    (tmp_path / "tallies.out").write_text(
        " ============================>     TALLY 7     <============================\n"
        "\n"
        " Cell 1\n"
        "   U235\n"
        "     Fission Rate                         0.25 +/- 0.01\n"
        "     (n,gamma)                            1.5e-02 +/- 3e-04\n"
        "   U238\n"
        "     Fission Rate                         0.05 +/- 0.002\n"
        "     (n,gamma)                            0.125 +/- 0.004\n"
        "     Some Very Long Score Name Of 40 Chars 2 +/- 0.5\n"
        " =======================>     TALLY 8: HEAT     <=======================\n"
        "\n"
        " Total Material\n"
        "   Heating                              -nan +/- inf\n")
    tally = evaluate(tmp_path, "tally")
    assert tally["7"] == {"fission_rate": [0.25, 0.05], "n_gamma": [0.015, 0.125],
                          "some_very_long_score_name_of_40_chars": 2.0}
    assert str(tally["8"]["heating"]) == "nan"
    assert evaluate(tmp_path, "tally_std")["7"]["n_gamma"] == [3e-4, 0.004]


def test_model_json_is_generated():
    """.fz/models/OpenMC.json is the output of scripts/make_model.py."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("make_model", ROOT / "scripts" / "make_model.py")
    make_model = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(make_model)
    assert (ROOT / ".fz" / "models" / "OpenMC.json").read_text() == make_model.render()
