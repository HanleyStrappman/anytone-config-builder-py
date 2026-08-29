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
"""Regression test: the four generated CSVs, over the whole flag matrix.

Runs the builder on the real PNW inputs in the repo root -- as they are, with the
over-long zone name still in them -- for all 30 combinations of --sorting,
--nicknames and --hotspot-tx-permit, and checks exit status, messages and the
content of every generated file against the recorded goldens.

Full copies of the default combination's output are kept under golden/default/ so
there is something to actually read a diff against; the other 29 are compared by
digest, which would otherwise cost ~28MB of near-identical CSVs.

    python3 tests/test_output_regression.py            # check
    python3 tests/test_output_regression.py --update   # re-record
"""
import filecmp
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _golden import (GOLDEN, OUTPUTS, REAL_INPUTS, REPO, compare, digests, load,
                     report, run, save, updating)

DEFAULT_COMBO = "alpha.off.same-color-code"
FULL_COPIES = os.path.join(GOLDEN, "default")

COMBOS = [(s, n, h)
          for s in ("alpha", "repeaters-first", "analog-first")
          for n in ("off", "prefix", "suffix", "prefix-forced", "suffix-forced")
          for h in ("always", "same-color-code")]


def real_args(outdir, extra):
    args = [f"--{flag}-csv={os.path.join(REPO, name)}"
            for flag, name in REAL_INPUTS.items()]
    return args + [f"--config={os.path.join(REPO, 'config')}",
                   f"--output-directory={outdir}"] + list(extra)


def record_combo(work, sort, nick, hot):
    tag = f"{sort}.{nick}.{hot}"
    outdir = os.path.join(work, tag)
    os.makedirs(outdir)
    extra = [f"--sorting={sort}", f"--nicknames={nick}", f"--hotspot-tx-permit={hot}"]
    rc, out = run(real_args(outdir, extra), {REPO: "<repo>", outdir: "<out>"})
    return tag, outdir, {"exit": rc, "output": out, "files": digests(outdir)}


work = tempfile.mkdtemp(prefix="acb-outreg-")
actual, dirs = {}, {}
for sort, nick, hot in COMBOS:
    tag, outdir, record = record_combo(work, sort, nick, hot)
    actual[tag] = record
    dirs[tag] = outdir

if updating():
    save("outputs.json", actual)
    shutil.rmtree(FULL_COPIES, ignore_errors=True)
    os.makedirs(FULL_COPIES)
    for name in OUTPUTS:
        shutil.copy(os.path.join(dirs[DEFAULT_COMBO], name), FULL_COPIES)
    print(f"recorded {len(OUTPUTS)} full files under "
          f"{os.path.relpath(FULL_COPIES, REPO)} ({DEFAULT_COMBO})")
    shutil.rmtree(work, ignore_errors=True)
    sys.exit(0)

expected = load("outputs.json")
results = []
for tag in sorted(actual):
    problems = compare(expected.get(tag, {}), actual[tag])
    if tag not in expected:
        problems = [f"no golden recorded for this combination"]
    results.append((tag, problems))

# The default combination is also held as full files, so a digest mismatch there
# can be turned into a readable diff instead of two hex strings.
for name in OUTPUTS:
    golden_file = os.path.join(FULL_COPIES, name)
    fresh = os.path.join(dirs[DEFAULT_COMBO], name)
    if not os.path.exists(golden_file):
        results.append((f"default/{name}", ["no full copy recorded"]))
    elif not filecmp.cmp(golden_file, fresh, shallow=False):
        results.append((f"default/{name}",
                        [f"differs from {os.path.relpath(golden_file, REPO)}; "
                         f"diff it against {fresh}"]))
    else:
        results.append((f"default/{name}", []))

code = report(results, "flag combinations")
shutil.rmtree(work, ignore_errors=True)
sys.exit(code)
