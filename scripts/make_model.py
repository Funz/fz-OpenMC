#!/usr/bin/env python3
"""Writes .fz/models/OpenMC.json (the output expressions are generated here, as
one-line fz python:// expressions are hard to edit by hand).

Usage: python scripts/make_model.py [output file]   (default: .fz/models/OpenMC.json)

fz evaluates a python:// expression with eval() and its helpers as *local*
names, which nested lambdas and comprehensions cannot see: each expression is
therefore wrapped in a lambda taking re, read and base_dir as arguments.
"""
import json
import sys
from pathlib import Path

# Text of the OpenMC terminal output: openmc.log (written by OpenMC.sh), else
# fz's out.txt (run with a plain "sh://openmc" calculator); None if both are
# missing or empty
LOG = ("(lambda f: read(f).replace('\\r\\n', '\\n') if f else None)"
       "(next((f for f in ('openmc.log', 'out.txt') "
       "if (base_dir / f).is_file() and (base_dir / f).stat().st_size), None))")

# First error found, else NORMAL END when the RESULTS banner was printed
STATUS = (
    "(lambda t: 'NO OUTPUT' if t is None else "
    # " ERROR: <message>", continuation lines indented by 8 blanks
    "'ERROR: ' + ' '.join(m.group(1).split()) "
    "if (m := re.search(r'^ ERROR: (.*(?:\\n {8}\\S.*)*)', t, re.M)) else "
    # uncaught C++ exception (e.g. a malformed XML value)
    "'CRASH: ' + m.group(1).strip() "
    "if (m := re.search(r'^ +what\\(\\): +(.*)$', t, re.M)) else "
    # Python input script failure: last line of the traceback
    "'PYTHON ERROR: ' + m.group(1).strip() "
    "if (m := re.search(r'^Traceback \\(most recent call last\\):\\n(?:[ \\t].*\\n)*(\\S.*)', t, re.M)) else "
    "'NORMAL END' if re.search(r'^ =+> +RESULTS +<=+', t, re.M) else 'NO END BANNER')"
    "(" + LOG + ")")


def result(label, group):
    """Last ' <label> = <mean> +/- <std>' line of the RESULTS block (group 1:
    mean, 2: std; the std is missing with a single active batch)."""
    return ("(lambda t: (lambda v: float(v[-1]) if v and v[-1] else None)"
            "([m.group(" + str(group) + ") for m in re.finditer(r'^ " + label
            + r" += +(\S+)(?: +\+/- +(\S+))?', t, re.M)]) if t else None)(" + LOG + ")")


def tallies(group):
    """{tally id: {score: value or list over the bins}} from tallies.out
    (group 1: mean, 2: std); score names in lowercase with '_' for any other
    character ('Fission Rate' -> fission_rate)."""
    return (
        "(lambda t: {m.group(1): "
        "(lambda d: {k: v[0] if len(v) == 1 else v for k, v in d.items()})"
        "((lambda d: [d.setdefault(re.sub(r'[^0-9a-z]+', '_', s.lower()).strip('_'), [])"
        ".append(float((x, e)[" + str(group - 1) + "])) "
        "for s, x, e in re.findall(r'^ +(\\S.*?) +(\\S+) +\\+/- +(\\S+) *$', m.group(2), re.M)] and d)({}) or {}) "
        "for m in re.finditer(r'^ =+> +TALLY (\\d+)\\b.*\\n((?:(?! =+> ).*\\n?)*)', t, re.M)})"
        "(read('tallies.out').replace('\\r\\n', '\\n') if (base_dir / 'tallies.out').is_file() else '')")


def wrap(expr):
    return "python://(lambda re, read, base_dir: " + expr + ")(re, read, base_dir)"


MODEL = {
    "id": "OpenMC",
    "varprefix": "$",
    "formulaprefix": "@",
    "delim": "{}",
    "commentline": "#",
    "output": {
        "openmc_status": wrap(STATUS),
        "keff": wrap(result("Combined k-effective", 1)),
        "keff_std": wrap(result("Combined k-effective", 2)),
        "leakage": wrap(result("Leakage Fraction", 1)),
        "leakage_std": wrap(result("Leakage Fraction", 2)),
        "tally": wrap(tallies(1)),
        "tally_std": wrap(tallies(2)),
    },
}


def render():
    return json.dumps(MODEL, indent=4) + "\n"


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else
               Path(__file__).resolve().parents[1] / ".fz" / "models" / "OpenMC.json")
    out.write_text(render())
    print(f"written: {out}")
