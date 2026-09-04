#!/usr/bin/env python3
#
# Anytone config builder -- test suite.
#
# Copyright (C) 2026 Scott Robinson (AG7T)
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A
# PARTICULAR PURPOSE.  See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with
# this program.  If not, see <https://www.gnu.org/licenses/>.
"""Regression test: command-line handling.

The port reproduces Getopt::Long's habits deliberately -- unknown options warn on
stderr and stop, stray non-option arguments are ignored, `--` ends parsing, and
unique prefixes of an option name are accepted.  These cases pin that down.

    python3 tests/test_args_regression.py            # check
    python3 tests/test_args_regression.py --update   # re-record
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _golden import (CONFIG, FIXTURES, REPO, compare, digests, load, report, run,
                     save, updating)



def valid(indir):
    return [f"--analog-csv={indir}/analog.csv",
            f"--digital-others-csv={indir}/others.csv",
            f"--digital-repeaters-csv={indir}/repeaters.csv",
            f"--talkgroups-csv={indir}/talkgroups.csv",
            f"--config={CONFIG}"]


# name -> (argv built from the valid set, whether to pass --output-directory)
def cases(indir):
    v = valid(indir)
    return {
        "no-args":            ([], False),
        "unknown-long":       (v + ["--bogus"], True),
        "unknown-uppercase":  (v + ["--BoGuS"], True),
        "unknown-with-value": (v + ["--bogus=1"], True),
        "unknown-short":      (v + ["-x"], True),
        "stray-positional":   (v + ["stray.txt"], True),
        "two-positionals":    (v + ["a.txt", "b.txt"], True),
        "double-dash":        (v + ["--"], True),
        "abbrev-sort":        (v + ["--sort=repeaters-first"], True),
        "abbrev-nick":        (v + ["--nick=prefix"], True),
        "abbrev-hotspot":     (v + ["--hotspot=always"], True),
        "space-separated":    ([a for pair in (x.split("=", 1) for x in v) for a in pair], True),
        "missing-analog-arg": ([a for a in v if not a.startswith("--analog-csv")], True),
        "missing-outdir":     (v, False),
        "no-config-flag":     ([a for a in v if not a.startswith("--config")], True),
        "empty-config-value": ([a for a in v if not a.startswith("--config")] + ["--config="], True),
        "cps-format-0":       (v + ["--cps-format=0"], True),
        "cps-format-2":       (v + ["--cps-format=2"], True),
        "cps-format-3":       (v + ["--cps-format=3"], True),
        "cps-format-4":       (v + ["--cps-format=4"], True),
        "cps-format-unknown": (v + ["--cps-format=9"], True),
        "abbrev-cps-format":  (v + ["--cps=3"], True),
        # Airband is optional everywhere.  Format 3 reads it; the others still
        # write the pair and warn, rather than refusing to build anything.
        "am-air-format-3":    (v + ["--cps-format=3", f"--am-air-csv={indir}/airband.csv"], True),
        "am-air-format-0":    (v + ["--cps-format=0", f"--am-air-csv={indir}/airband.csv"], True),
        "am-air-missing":     (v + [f"--am-air-csv={indir}/nope.csv"], True),
    }


work = tempfile.mkdtemp(prefix="acb-argreg-")
indir = os.path.join(work, "in")
shutil.copytree(FIXTURES, indir)

# Everything runs from the temp directory, which deliberately has no "config"
# subdirectory: that is what makes the no-config-flag case prove the defaults
# ship with the package, rather than proving the cwd happened to have a copy.
CWD = work

actual = {}
for name, (argv, needs_out) in cases(indir).items():
    outdir = os.path.join(work, name)
    os.makedirs(outdir)
    if needs_out:
        argv = argv + [f"--output-directory={outdir}"]
    rc, out = run(argv, {indir: "<in>", outdir: "<out>", REPO: "<repo>"}, cwd=CWD)
    actual[name] = {"exit": rc, "output": out, "files": digests(outdir)}

shutil.rmtree(work, ignore_errors=True)

if updating():
    save("args.json", actual)
    sys.exit(0)

expected = load("args.json")
results = [(name,
            ["no golden recorded for this case"] if name not in expected
            else compare(expected[name], actual[name]))
           for name in actual]
sys.exit(report(results, "command-line cases"))
