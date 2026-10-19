"""End-to-end runs through fz (fzr).

- with a fake openmc replaying a real OpenMC output: calculator alias
  discovery (localhost_OpenMC), arguments fz passes to OpenMC.sh, parsing;
- with a real OpenMC (skipped unless openmc is on PATH or OPENMC_CMD is set):
  both examples, multi-group mode, no nuclear data library needed.

Run: pytest tests/test_fz_e2e.py
"""

import os
import shutil
from pathlib import Path

import pytest

fz = pytest.importorskip("fz")

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "ok_eigenvalue"
REAL_OPENMC = os.environ.get("OPENMC_CMD") or shutil.which("openmc")

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="bash required")


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    shutil.copytree(ROOT / ".fz", tmp_path / ".fz")
    shutil.copytree(ROOT / "examples", tmp_path / "examples")
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def fake_openmc(workspace, monkeypatch):
    fake = workspace / "bin" / "openmc"
    fake.parent.mkdir()
    fake.write_text(
        "#!/bin/bash\n"
        "grep -q 'coeffs=\"0.0 0.0 0.0 20\"' model.xml || { echo ' ERROR: radius not substituted'; exit 255; }\n"
        f"cat '{FIXTURE / 'openmc.log'}'\n"
        f"cp '{FIXTURE / 'tallies.out'}' .\n"
        "touch statepoint.30.h5\n")
    fake.chmod(0o755)
    monkeypatch.setenv("OPENMC_CMD", str(fake))
    return fake


@pytest.mark.parametrize("calculators", ["localhost_OpenMC", None])
def test_fzr_fake(fake_openmc, workspace, calculators):
    kwargs = {"calculators": calculators} if calculators else {}
    results = fz.fzr("examples/sphere_xml", {"radius": [20]}, "OpenMC",
                     results_dir=str(workspace / "results"), **kwargs)
    row = results.iloc[0]
    assert row["status"] == "done", row.to_dict()
    assert row["openmc_status"] == "NORMAL END"
    assert row["keff"] == pytest.approx(1.02059)
    assert row["keff_std"] == pytest.approx(0.00834)
    assert row["tally_1_flux"] == [3.11693, 19.8263]
    assert row["tally_std_2_absorption_rate"] == pytest.approx(0.00591116)


def test_fzr_fake_failed_case(fake_openmc, workspace):
    """An OpenMC error makes the case fail, with the message in openmc_status."""
    results = fz.fzr("examples/sphere_xml", {"radius": [9]}, "OpenMC",
                     results_dir=str(workspace / "results"))
    row = results.iloc[0]
    assert row["status"] != "done"
    assert row["openmc_status"] == "ERROR: radius not substituted"


@pytest.mark.skipif(REAL_OPENMC is None, reason="OpenMC not installed (openmc on PATH or OPENMC_CMD)")
@pytest.mark.parametrize("example", ["sphere.py", "sphere_xml"])
def test_fzr_real_openmc(workspace, example):
    results = fz.fzr(f"examples/{example}", {"radius": [10, 30], "particles": 500}, "OpenMC",
                     results_dir=str(workspace / "results"))
    assert list(results["status"]) == ["done", "done"], results.to_dict()
    assert list(results["openmc_status"]) == ["NORMAL END", "NORMAL END"]
    small, large = results["keff"]
    # keff ~0.5 (r = 10 cm) and ~1.3 (r = 30 cm); keff_std ~0.01 with 500 particles
    assert 0.3 < small < 0.7 < 1.1 < large < 1.5
    assert all(0 < s < 0.05 for s in results["keff_std"])
    assert all(len(f) == 2 for f in results["tally_1_flux"])
