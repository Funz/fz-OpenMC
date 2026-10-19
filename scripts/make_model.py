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

# First OpenMC error: " ERROR: <message>" and its continuation lines. With
# several threads, OpenMC may print the message once per thread, the copies
# interleaved line by line, glued inside a line ("...definition. ERROR: More",
# "PleaseMore than", "ERROR:  ERROR:") or after the MPI abort lines: the text
# from the first " ERROR: " line up to a Python traceback or a crash report
# ("[host:pid] Caught signal") is cut at "ERROR:", at runs of 2 blanks or more
# (indentation of a glued line) and at the copies of the first piece, what
# follows "Abort(" is dropped, and each piece is kept once, in order: the
# message is read once and in full.
ERROR = (
    "(lambda ps: ' '.join(dict.fromkeys(y for p in ps "
    "for y in (z.strip() for z in re.split('(' + re.escape(ps[0]) + ')', p)) if y)) if ps else None)"
    "([' '.join(p.split()) for l in m.group(0).split('\\n') "
    "for p in re.split(r'ERROR:|\\s{2,}', l.split('Abort(')[0]) if p.strip()] "
    "if (m := re.search(r'^ ERROR: .*(?:\\n(?!Traceback |\\[| =+> | *WARNING: ).*)*', t, re.M)) else [])")

# First error found, else NORMAL END when the RESULTS banner was printed
STATUS = (
    "(lambda t: 'NO OUTPUT' if t is None else "
    "'ERROR: ' + e if (e := " + ERROR + ") else "
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


# Absolute path of the last statepoint file (highest batch number; zero-padded
# names with triggers), None if there is none: read it with the openmc API
STATEPOINT = (
    "(lambda f: str(f.resolve()) if f else None)"
    "(max(base_dir.glob('statepoint.*.h5'), default=None, "
    "key=lambda p: int(m.group(1)) if (m := re.search(r'\\.(\\d+)\\.h5$', p.name)) else -1))")


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
        "statepoint": wrap(STATEPOINT),
    },
}


def render():
    return json.dumps(MODEL, indent=4) + "\n"


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else
               Path(__file__).resolve().parents[1] / ".fz" / "models" / "OpenMC.json")
    out.write_text(render())
    print(f"written: {out}")
